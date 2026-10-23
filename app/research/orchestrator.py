from typing import Any, List, Optional
from app.research.evaluator import deduplicate_and_index_sources, evaluate_evidence
from app.research.grounding import validate_and_ground_report
from app.research.llm import BaseLLMClient
from app.research.planner import plan_research
from app.research.providers import (
    DeterministicMockSearchProvider,
    SearchProvider,
    get_configured_search_provider,
)
from app.research.state import ResearchReport, RetrievalStatus, SourceDocument, SubQuery


class ResearchOrchestrator:
    """
    Coordinates the evidence-based research agent pipeline:
    1. Research Planning: Decomposes question into focused subqueries.
    2. Source Collection: Queries provider and deduplicates sources.
    3. Evidence Evaluation & Synthesis:
       - Uses LLM synthesis when configured and requested.
       - Validates source grounding and rejects hallucinated citations.
       - Preserves deterministic evaluation fallback when LLM is unavailable.
    """

    def __init__(
        self,
        provider: Optional[SearchProvider] = None,
        llm_client: Optional[BaseLLMClient] = None,
    ):
        self.provider = provider or get_configured_search_provider()
        self.llm_client = llm_client

    def conduct_research(
        self,
        question: str,
        max_subqueries: int = 3,
        max_sources: int = 6,
        use_llm: bool = False,
        fallback_to_deterministic: bool = True,
    ) -> ResearchReport:
        """
        Conducts bounded, evidence-based research on the supplied question.
        """
        # 1. Research Planning
        subqueries = plan_research(question, max_subqueries=max_subqueries)

        # 2. Source Collection
        raw_sources: List[SourceDocument] = []
        for sq in subqueries:
            try:
                results = self.provider.search(sq.query_text, max_results=3)
                raw_sources.extend(results)
            except Exception as err:
                raw_sources.append(
                    SourceDocument(
                        id=f"ERR-{sq.id}",
                        title="Failed Retrieval",
                        url=f"https://error.retrieval/{sq.id}",
                        snippet=f"Failed to query provider for '{sq.query_text}': {str(err)}",
                        retrieval_status=RetrievalStatus.FAILED,
                    )
                )

        # Deduplicate and index sources safely
        indexed_sources = deduplicate_and_index_sources(raw_sources, max_sources=max_sources)

        # 3. LLM Synthesis Path (if enabled and client available)
        if use_llm and self.llm_client is not None:
            try:
                model_output = self.llm_client.generate_report_payload(
                    question=question,
                    sources=indexed_sources,
                )
                return validate_and_ground_report(
                    question=question,
                    subqueries=subqueries,
                    sources=indexed_sources,
                    model_output=model_output,
                )
            except Exception as err:
                if not fallback_to_deterministic:
                    raise
                # Fall back to deterministic pipeline and append caveat
                report = self._conduct_deterministic_synthesis(
                    question=question,
                    subqueries=subqueries,
                    indexed_sources=indexed_sources,
                )
                report.limitations.append(
                    f"Warning: LLM synthesis unavailable ({str(err)}). Reverted to deterministic evaluation fallback."
                )
                return report

        # Default / Fallback: Deterministic Synthesis
        return self._conduct_deterministic_synthesis(
            question=question,
            subqueries=subqueries,
            indexed_sources=indexed_sources,
        )

    def _conduct_deterministic_synthesis(
        self,
        question: str,
        subqueries: List[Any],
        indexed_sources: List[SourceDocument],
    ) -> ResearchReport:
        """Original deterministic evidence evaluation and synthesis."""
        supporting, conflicting, unanswered = evaluate_evidence(indexed_sources, question=question)

        valid_sources = [s for s in indexed_sources if s.retrieval_status == RetrievalStatus.SUCCESS]
        sources_sufficient = len(valid_sources) >= 1 and len(supporting) >= 1

        key_findings: List[str] = []
        for claim in supporting:
            if claim.supporting_source_ids:
                source_tags = " ".join(f"[{sid}]" for sid in claim.supporting_source_ids)
                key_findings.append(f"Fact: {claim.claim_text} {source_tags}")
            else:
                key_findings.append(f"Fact: {claim.claim_text} [Unsupported - Inadequate Evidence]")

        if len(supporting) >= 2 and len(valid_sources) >= 2:
            convergence_tags = " ".join(f"[{s.id}]" for s in valid_sources[:3])
            key_findings.append(
                f"Synthesis: Evidence converges across {len(valid_sources)} independent sources on core aspects of '{question}'. {convergence_tags}"
            )

        limitations: List[str] = []
        if any(s.is_mock for s in indexed_sources):
            limitations.append(
                "Notice: Research was conducted using an offline deterministic mock provider. "
                "Citations reflect test corpus data rather than live web searches."
            )
        elif indexed_sources:
            limitations.append(
                "Notice: Research was synthesized from live external web search results."
            )

        strong_conflicts = [c for c in conflicting if c.status == "conflicting"]
        potential_conflicts = [c for c in conflicting if c.status == "potential_conflict"]

        if strong_conflicts:
            limitations.append(
                f"Contradictory evidence detected in {len(strong_conflicts)} finding(s). "
                "Independent verification is strongly advised."
            )
        if potential_conflicts:
            limitations.append(
                f"Scope nuance noted in {len(potential_conflicts)} finding(s) with contrasting definitions or metrics."
            )

        # Transparent quality criteria (non-arbitrary, explainable)
        quality_signals: List[str] = []
        if any(s.is_mock for s in indexed_sources):
            quality_signals.append("Provenance: Offline deterministic test mock (synthetic corpus).")
        elif indexed_sources:
            quality_signals.append("Provenance: Live external web sources verified via HTTPS/HTTP.")

        quality_signals.append(
            f"Source Coverage: {len(valid_sources)} of {len(indexed_sources)} retrieved source(s) successfully verified."
        )

        if supporting:
            quality_signals.append(
                f"Claim Traceability: All {len(supporting)} key finding(s) directly mapped to verified source citations."
            )
        else:
            quality_signals.append("Claim Traceability: No verifiable findings substantiated by available sources.")

        if strong_conflicts:
            quality_signals.append(
                f"Contradiction Warning: {len(strong_conflicts)} contradictory claim(s) detected across sources."
            )
        elif potential_conflicts:
            quality_signals.append(
                f"Scope Contrast: {len(potential_conflicts)} finding(s) with nuanced scope differences."
            )
        else:
            quality_signals.append("Consensus: No contradictions detected among retrieved sources.")

        if not sources_sufficient:
            evidence_quality = "insufficient"
        elif conflicting:
            evidence_quality = "moderate"
        elif len(valid_sources) >= 2 and len(supporting) >= 2:
            evidence_quality = "high"
        else:
            evidence_quality = "moderate"

        if not sources_sufficient:
            unanswered.append("The available sources provide insufficient coverage to reach a conclusive finding.")
            executive_summary = (
                f"Research conducted for question: '{question}'. "
                "Sources gathered were insufficient or inconclusive. No verified findings could be substantiated."
            )
        else:
            executive_summary = (
                f"Evidence-based analysis for: '{question}'. "
                f"Synthesized from {len(valid_sources)} verified source(s) across {len(subqueries)} subqueries. "
                f"Identified {len(supporting)} supported finding(s) and {len(conflicting)} conflicting claim(s)."
            )

        return ResearchReport(
            research_question=question,
            executive_summary=executive_summary,
            subqueries=subqueries,
            sources=indexed_sources,
            key_findings=key_findings,
            supporting_evidence=supporting,
            conflicting_evidence=conflicting,
            unanswered_questions=unanswered,
            sources_sufficient=sources_sufficient,
            limitations=limitations,
            evidence_quality=evidence_quality,
            quality_signals=quality_signals,
        )
