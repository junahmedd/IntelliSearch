import re
from typing import Any, Dict, List, Set
from app.research.state import EvidenceClaim, ResearchReport


def _normalize_finding_text(text: str) -> str:
    """
    Strips citation tags (e.g. [S1], [WEB-1], [TAVILY-1], [MOCK-1], [Unsupported...]),
    structural prefixes (Fact:, Synthesis:, Inference:), and extra whitespace for robust comparison.
    """
    cleaned = re.sub(r"\[(S\d+|WEB-\d+|TAVILY-\d+|MOCK-\d+|Unsupported[^\]]*)\]", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(fact|synthesis|inference):\s*", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.strip().lower().split())


def compare_research_reports(
    report_a: ResearchReport,
    report_b: ResearchReport,
    id_a: str,
    id_b: str,
) -> Dict[str, Any]:
    """
    Deterministically compares two research reports.
    Identifies shared findings, unique findings to each report,
    conflicting evidence, available sources, and methodological limitations.
    """
    # 1. Compare findings deterministically
    norm_map_a = {_normalize_finding_text(f): f for f in report_a.key_findings}
    norm_map_b = {_normalize_finding_text(f): f for f in report_b.key_findings}

    norm_keys_a = set(norm_map_a.keys())
    norm_keys_b = set(norm_map_b.keys())

    shared_norm = norm_keys_a.intersection(norm_keys_b)
    only_a_norm = norm_keys_a - norm_keys_b
    only_b_norm = norm_keys_b - norm_keys_a

    shared_findings = [norm_map_a[k] for k in shared_norm]
    findings_only_in_a = [norm_map_a[k] for k in only_a_norm]
    findings_only_in_b = [norm_map_b[k] for k in only_b_norm]

    # 2. Extract conflicting claims
    all_conflicts: List[EvidenceClaim] = []
    seen_conflict_texts: Set[str] = set()

    for c in list(report_a.conflicting_evidence) + list(report_b.conflicting_evidence):
        if c.claim_text not in seen_conflict_texts:
            seen_conflict_texts.add(c.claim_text)
            all_conflicts.append(c)

    # 3. Compile sources metadata
    sources_a = [
        {"id": s.id, "title": s.title, "url": s.url, "is_mock": s.is_mock}
        for s in report_a.sources
    ]
    sources_b = [
        {"id": s.id, "title": s.title, "url": s.url, "is_mock": s.is_mock}
        for s in report_b.sources
    ]

    # 4. Summary synthesis
    summary = (
        f"Comparison between '{id_a}' ('{report_a.research_question}') and '{id_b}' ('{report_b.research_question}'): "
        f"Found {len(shared_findings)} shared finding(s), {len(findings_only_in_a)} finding(s) unique to report A, "
        f"{len(findings_only_in_b)} finding(s) unique to report B, and {len(all_conflicts)} conflicting claim(s) requiring review."
    )

    return {
        "id_a": id_a,
        "id_b": id_b,
        "question_a": report_a.research_question,
        "question_b": report_b.research_question,
        "shared_findings": shared_findings,
        "findings_only_in_a": findings_only_in_a,
        "findings_only_in_b": findings_only_in_b,
        "conflicting_claims": all_conflicts,
        "sources_a": sources_a,
        "sources_b": sources_b,
        "limitations_a": report_a.limitations,
        "limitations_b": report_b.limitations,
        "comparison_summary": summary,
    }
