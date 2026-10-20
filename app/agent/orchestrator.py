import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.agent.state import (
    EvidenceItem,
    InvestigationReport,
    InvestigationStep,
    ToolName,
    ToolObservation,
)
from app.tools.code_search import search_code
from app.tools.project_inspector import list_project_files, resolve_safe_path

# Common English stop words to filter out from bug descriptions
COMMON_STOP_WORDS: Set[str] = {
    "the", "a", "an", "and", "or", "is", "in", "it", "to", "for", "with", "from",
    "that", "this", "these", "those", "when", "does", "not", "why", "how", "what",
    "bug", "issue", "error", "fails", "failing", "failure", "broken", "returns",
    "return", "expected", "got", "get", "getting", "when", "while", "code", "file",
    "user", "report", "reported",
}


def extract_candidate_search_terms(description: str) -> List[str]:
    """
    Extracts high-signal technical terms, function names, identifiers,
    and quoted phrases from a bug description.
    """
    if not description:
        return []

    candidates: List[str] = []

    # 1. Quoted terms (highest priority, captures phrases like 'Invalid token provided')
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", description)
    for q in quoted:
        cleaned = q.strip()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

    # 2. Explicit function calls like func_name()
    calls = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\(\)", description)
    for c in calls:
        if c not in candidates and c.lower() not in COMMON_STOP_WORDS:
            candidates.append(c)

    # 3. Dotted paths or filenames like module.func or auth.py
    dotted = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)\b", description)
    for d in dotted:
        parts = d.split(".")
        for p in parts:
            if p not in candidates and p.lower() not in COMMON_STOP_WORDS and len(p) >= 3:
                candidates.append(p)

    # 4. CamelCase or snake_case identifiers (e.g. ZeroDivisionError, read_health, authenticate_user)
    identifiers = re.findall(r"\b(?:[A-Z][a-z0-9]+[A-Z][a-zA-Z0-9]*|[a-z0-9]+_[a-z0-9_]+)\b", description)
    for ident in identifiers:
        if ident not in candidates and ident.lower() not in COMMON_STOP_WORDS:
            candidates.append(ident)

    # 5. Fallback: individual meaningful words of length >= 4 only if no symbols were extracted
    if not candidates:
        words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b", description)
        for w in words:
            if w.lower() not in COMMON_STOP_WORDS and w not in candidates:
                candidates.append(w)

    return candidates


class DeterministicDecisionPolicy:
    """
    A deterministic, bounded decision policy for investigating codebases.
    Decoupled from orchestrator execution so it can be swapped with an LLM later.
    """

    def __init__(self, bug_description: str):
        self.bug_description = bug_description
        self.has_inspected_files = False
        self.candidate_terms = extract_candidate_search_terms(bug_description)
        self.searched_terms: Set[str] = set()

    def decide_next_action(
        self,
        step_number: int,
        max_steps: int,
        last_observation: Optional[ToolObservation] = None,
        observed_evidence_count: int = 0,
    ) -> Tuple[str, ToolName, Dict[str, Any]]:
        """
        Decides the next action to take based on current investigation state
        and previous observations.
        """
        if step_number > max_steps:
            return (
                "Maximum investigation steps reached. Ending investigation.",
                ToolName.FINISH,
                {},
            )

        # Step 1: Inspect project structure to discover available files
        if not self.has_inspected_files:
            self.has_inspected_files = True
            return (
                "Inspect the project directory to map the codebase layout and locate Python files.",
                ToolName.INSPECT_PROJECT,
                {},
            )

        # Subsequent steps: search for candidate terms in priority order
        for term in self.candidate_terms:
            if term not in self.searched_terms:
                self.searched_terms.add(term)
                return (
                    f"Search the Python source files for candidate symbol or keyword '{term}'.",
                    ToolName.SEARCH_CODE,
                    {"query": term},
                )

        return (
            "All candidate search terms have been investigated. Concluding investigation.",
            ToolName.FINISH,
            {},
        )


class InvestigationOrchestrator:
    """
    Coordinates an agent investigation workflow:
    - Runs bounded steps (governed by decision policy)
    - Captures factual observations
    - Maintains strict separation between evidence and hypothesis
    """

    def __init__(self, policy: Optional[DeterministicDecisionPolicy] = None):
        self.policy = policy

    def run(
        self,
        bug_description: str,
        project_root: str | Path,
        max_steps: int = 5,
        base_dir: Optional[str | Path] = None,
    ) -> InvestigationReport:
        """
        Executes a bounded investigation on a target project root.
        """
        if not bug_description or not bug_description.strip():
            raise ValueError("Bug description cannot be empty.")

        if max_steps < 1:
            raise ValueError("max_steps must be at least 1.")

        resolved_root = resolve_safe_path(project_root, base_dir=base_dir)

        # Initialize policy if not injected
        policy = self.policy or DeterministicDecisionPolicy(bug_description)

        steps_taken: List[InvestigationStep] = []
        observed_evidence: List[EvidenceItem] = []
        seen_evidence_keys: Set[Tuple[str, int]] = set()

        step_counter = 1
        last_obs: Optional[ToolObservation] = None
        status = "completed"

        while step_counter <= max_steps:
            thought, tool_name, params = policy.decide_next_action(
                step_number=step_counter,
                max_steps=max_steps,
                last_observation=last_obs,
                observed_evidence_count=len(observed_evidence),
            )

            if tool_name == ToolName.FINISH:
                status = "completed"
                break

            # Execute the chosen tool safely
            obs = self._execute_tool(
                tool_name=tool_name,
                params=params,
                project_root=resolved_root,
                base_dir=base_dir,
            )
            last_obs = obs

            step = InvestigationStep(
                step_number=step_counter,
                thought=thought,
                action=tool_name.value,
                parameters=params,
                observation=obs,
            )
            steps_taken.append(step)

            # Collect evidence if search returned matches
            if (
                tool_name == ToolName.SEARCH_CODE
                and obs.success
                and obs.data
                and "matches" in obs.data
            ):
                query = params.get("query", "")
                for match in obs.data["matches"]:
                    evidence_key = (match["file"], match["line_number"])
                    if evidence_key not in seen_evidence_keys:
                        seen_evidence_keys.add(evidence_key)
                        observed_evidence.append(
                            EvidenceItem(
                                file=match["file"],
                                line_number=match["line_number"],
                                line_content=match["line_content"],
                                search_query=query,
                            )
                        )

            step_counter += 1
        else:
            # If the loop finished without encountering ToolName.FINISH
            status = "max_steps_reached"

        # Synthesize report while strictly separating evidence from hypothesis
        suspected_root_cause, summary = self._synthesize_findings(
            bug_description=bug_description,
            observed_evidence=observed_evidence,
            steps_taken=steps_taken,
            status=status,
        )

        return InvestigationReport(
            bug_description=bug_description,
            status=status,
            total_steps=len(steps_taken),
            steps_taken=steps_taken,
            observed_evidence=observed_evidence,
            suspected_root_cause=suspected_root_cause,
            summary=summary,
        )

    def _execute_tool(
        self,
        tool_name: ToolName,
        params: Dict[str, Any],
        project_root: Path,
        base_dir: Optional[str | Path],
    ) -> ToolObservation:
        """Executes a tool and catches errors safely."""
        try:
            if tool_name == ToolName.INSPECT_PROJECT:
                data = list_project_files(
                    project_root=project_root,
                    base_dir=base_dir,
                )
                return ToolObservation(
                    tool_name=tool_name.value,
                    parameters=params,
                    success=True,
                    data=data,
                )
            elif tool_name == ToolName.SEARCH_CODE:
                query = params.get("query", "")
                data = search_code(
                    project_root=project_root,
                    query=query,
                    base_dir=base_dir,
                )
                return ToolObservation(
                    tool_name=tool_name.value,
                    parameters=params,
                    success=True,
                    data=data,
                )
            else:
                return ToolObservation(
                    tool_name=tool_name.value,
                    parameters=params,
                    success=False,
                    error=f"Unsupported tool: {tool_name}",
                )
        except Exception as err:
            return ToolObservation(
                tool_name=tool_name.value,
                parameters=params,
                success=False,
                error=str(err),
            )

    def _synthesize_findings(
        self,
        bug_description: str,
        observed_evidence: List[EvidenceItem],
        steps_taken: List[InvestigationStep],
        status: str,
    ) -> Tuple[Optional[str], str]:
        """
        Synthesizes observations into hypothesis and summary.
        Maintains clear distinction between factual evidence and suspected hypothesis.
        """
        if observed_evidence:
            matched_files = sorted({e.file for e in observed_evidence})
            matched_queries = sorted({e.search_query for e in observed_evidence})

            suspected_root_cause = (
                f"Candidate symbols ({', '.join(matched_queries)}) were located in "
                f"{', '.join(matched_files)}. These code locations may relate to the reported issue "
                f"'{bug_description}', but root cause requires manual verification."
            )
            summary = (
                f"Investigation completed across {len(steps_taken)} step(s). Found {len(observed_evidence)} "
                f"matching evidence line(s) across {len(matched_files)} file(s)."
            )
        else:
            suspected_root_cause = (
                "No direct source code matches were found for candidate terms extracted from the bug description. "
                "The issue may be triggered by runtime data, environment configurations, or external dependencies."
            )
            summary = (
                f"Investigation concluded after {len(steps_taken)} step(s). No direct evidence was located "
                "in Python source files."
            )

        if status == "max_steps_reached":
            summary += " Note: Maximum step limit reached before all candidate searches finished."

        return suspected_root_cause, summary
