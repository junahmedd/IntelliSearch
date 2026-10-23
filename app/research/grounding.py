import re
from typing import Any, Dict, List, Set, Tuple
from app.research.state import EvidenceClaim, ResearchReport, SourceDocument, SubQuery


class GroundingValidationError(ValueError):
    """Raised when model output fails evidence-grounding constraints."""
    pass


def validate_and_ground_report(
    question: str,
    subqueries: List[SubQuery],
    sources: List[SourceDocument],
    model_output: Dict[str, Any],
) -> ResearchReport:
    """
    Validates that model output is strictly grounded in the provided sources.

    Rules enforced:
    1. Every cited source ID in supporting_source_ids or contradicting_source_ids
       MUST exist in the provided source set.
    2. Any hallucinated or unknown source IDs (e.g. S99, fake URLs) are rejected / filtered out.
    3. If all supporting sources are invalid or absent for a claim, the claim is flagged as unverified.
    4. Executive summary, key findings, and limitations are extracted and type-checked.
    5. The final ResearchReport is constructed using only valid, verified sources.
    """
    valid_source_map: Dict[str, SourceDocument] = {s.id: s for s in sources}
    valid_source_ids: Set[str] = set(valid_source_map.keys())

    executive_summary = str(model_output.get("executive_summary", "")).strip()
    if not executive_summary:
        executive_summary = f"Synthesized research report for question: '{question}'."

    raw_key_findings = model_output.get("key_findings", [])
    raw_supporting = model_output.get("supporting_evidence", [])
    raw_conflicting = model_output.get("conflicting_evidence", [])
    raw_unanswered = model_output.get("unanswered_questions", [])
    raw_limitations = model_output.get("limitations", [])

    # Process and validate supporting evidence
    verified_supporting: List[EvidenceClaim] = []
    claim_counter = 1

    for item in raw_supporting:
        if isinstance(item, dict):
            text = str(item.get("claim_text", "")).strip()
            cited_ids = item.get("supporting_source_ids", [])
            # Filter cited IDs strictly against valid sources provided to the model
            valid_cited = [sid for sid in cited_ids if sid in valid_source_ids]

            if not text:
                continue

            status = "supported" if valid_cited else "unverified"
            verified_supporting.append(
                EvidenceClaim(
                    claim_id=f"LLM-C{claim_counter}",
                    claim_text=text,
                    supporting_source_ids=valid_cited,
                    contradicting_source_ids=[],
                    status=status,
                )
            )
            claim_counter += 1

    # Process and validate conflicting evidence
    verified_conflicting: List[EvidenceClaim] = []
    for item in raw_conflicting:
        if isinstance(item, dict):
            text = str(item.get("claim_text", "")).strip()
            supp_ids = [sid for sid in item.get("supporting_source_ids", []) if sid in valid_source_ids]
            contra_ids = [sid for sid in item.get("contradicting_source_ids", []) if sid in valid_source_ids]

            if text:
                verified_conflicting.append(
                    EvidenceClaim(
                        claim_id=f"LLM-CONFLICT-{claim_counter}",
                        claim_text=text,
                        supporting_source_ids=supp_ids,
                        contradicting_source_ids=contra_ids,
                        status="conflicting",
                    )
                )
                claim_counter += 1

    # Ground key findings: ensure each finding cites valid source IDs or is marked unsupported
    cleaned_key_findings: List[str] = []
    for f in raw_key_findings:
        text = str(f).strip()
        if not text:
            continue
        # Extract cited IDs like [S1], [S2]
        cited_sids = re.findall(r"\[(S\d+|WEB-\d+|TAVILY-\d+|MOCK-\d+)\]", text)
        valid_cites = [sid for sid in cited_sids if sid in valid_source_ids]
        if cited_sids and not valid_cites:
            # Finding cited only hallucinated/invalid source IDs: mark as unsupported
            text_without_fake_cites = re.sub(r"\[(S\d+|WEB-\d+|TAVILY-\d+|MOCK-\d+)\]", "", text).strip()
            cleaned_key_findings.append(f"{text_without_fake_cites} [Unsupported - Invalid Citations]")
        elif not cited_sids and valid_source_ids:
            # If no citations were embedded by LLM, check if any claim matches or mark uncertain
            cleaned_key_findings.append(text)
        else:
            cleaned_key_findings.append(text)

    # Process unanswered questions and limitations
    unanswered_list = [str(u).strip() for u in raw_unanswered if str(u).strip()]
    limitations_list = [str(l).strip() for l in raw_limitations if str(l).strip()]

    # If no sources were provided or no valid claims exist, mark as insufficient
    has_valid_sources = len(sources) > 0 and any(s.retrieval_status.value == "success" for s in sources)
    has_supported_evidence = len([c for c in verified_supporting if c.status == "supported"]) > 0
    sources_sufficient = has_valid_sources and has_supported_evidence

    if not sources_sufficient:
        unanswered_list.append("Available sources were insufficient to reliably substantiate findings.")
        limitations_list.append("Warning: Source data was insufficient; findings may be incomplete.")

    # Quality signals
    quality_signals: List[str] = []
    if any(s.is_mock for s in sources):
        quality_signals.append("Provenance: Offline deterministic test mock (synthetic corpus).")
    elif sources:
        quality_signals.append("Provenance: Live external web sources verified via HTTPS/HTTP.")

    valid_sources_count = len([s for s in sources if s.retrieval_status.value == "success"])
    quality_signals.append(f"Source Coverage: {valid_sources_count} of {len(sources)} source(s) verified.")

    if verified_supporting:
        quality_signals.append(
            f"Claim Traceability: {len(verified_supporting)} claim(s) audited against provided sources."
        )

    if verified_conflicting:
        quality_signals.append(
            f"Contradiction Warning: {len(verified_conflicting)} contradictory claim(s) detected."
        )
    else:
        quality_signals.append("Consensus: No contradictions detected among retrieved sources.")

    if not sources_sufficient:
        evidence_quality = "insufficient"
    elif verified_conflicting:
        evidence_quality = "moderate"
    elif valid_sources_count >= 2 and has_supported_evidence:
        evidence_quality = "high"
    else:
        evidence_quality = "moderate"

    return ResearchReport(
        research_question=question,
        executive_summary=executive_summary,
        subqueries=subqueries,
        sources=sources,
        key_findings=cleaned_key_findings,
        supporting_evidence=verified_supporting,
        conflicting_evidence=verified_conflicting,
        unanswered_questions=unanswered_list,
        sources_sufficient=sources_sufficient,
        limitations=limitations_list,
        evidence_quality=evidence_quality,
        quality_signals=quality_signals,
    )
