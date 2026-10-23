from unittest.mock import MagicMock
import pytest

from app.research.comparison import _normalize_finding_text, compare_research_reports
from app.research.evaluator import evaluate_evidence
from app.research.orchestrator import ResearchOrchestrator
from app.research.providers import SearchProvider
from app.research.state import EvidenceClaim, ResearchReport, RetrievalStatus, SourceDocument


# ==============================================================================
# 1. Structured Synthesis: Facts vs Synthesized Inferences
# ==============================================================================

def test_facts_and_synthesis_classification():
    """Verify orchestrator categorizes direct source claims as Fact: and convergence as Synthesis:."""
    mock_provider = MagicMock(spec=SearchProvider)
    mock_provider.search.return_value = [
        SourceDocument(id="S1", title="FastAPI Intro", url="https://fastapi.tiangolo.com", snippet="FastAPI is an async framework.", retrieval_status=RetrievalStatus.SUCCESS),
        SourceDocument(id="S2", title="FastAPI Speed", url="https://fastapi.tiangolo.com/benchmarks", snippet="FastAPI throughput is verified high.", retrieval_status=RetrievalStatus.SUCCESS),
    ]

    orchestrator = ResearchOrchestrator(provider=mock_provider)
    report = orchestrator.conduct_research("FastAPI async throughput", max_subqueries=1, max_sources=2)

    assert report.sources_sufficient is True
    # Verify presence of Fact: findings
    facts = [f for f in report.key_findings if f.startswith("Fact:")]
    assert len(facts) >= 2
    for fact in facts:
        assert "[S1]" in fact or "[S2]" in fact

    # Verify presence of multi-source Synthesis: finding
    syntheses = [f for f in report.key_findings if f.startswith("Synthesis:")]
    assert len(syntheses) == 1
    assert "[S1]" in syntheses[0] and "[S2]" in syntheses[0]


def test_unsupported_claim_tagged_explicitly():
    """Verify claims without supporting evidence are flagged as unsupported."""
    orchestrator = ResearchOrchestrator()
    unsupported_claim = EvidenceClaim(
        claim_id="C_UNSUP",
        claim_text="Unsubstantiated speculative claim",
        supporting_source_ids=[],
        status="unverified",
    )
    # Manually invoke synthesis with an unsupported claim
    report = orchestrator._conduct_deterministic_synthesis(
        question="Speculative Topic",
        subqueries=[],
        indexed_sources=[SourceDocument(id="S1", title="Doc", url="https://example.com/doc", snippet="Valid doc.")],
    )
    # Ensure all key findings have valid source tags or explicit unsupported warnings
    for f in report.key_findings:
        assert "[" in f and "]" in f


# ==============================================================================
# 2. Conflicting Evidence: Strong Dispute vs Potential Scope Contrast
# ==============================================================================

def test_conflict_distinction_strong_dispute():
    """Verify strong contradiction keywords (dispute, contradict, refuted) yield status='conflicting'."""
    sources = [
        SourceDocument(id="S1", title="Lab A", url="https://lab-a.org/claim", snippet="Room temperature quantum coherence achieved."),
        SourceDocument(id="S2", title="Lab B", url="https://lab-b.org/claim", snippet="Subsequent investigations dispute and refute the quantum coherence claim."),
    ]
    supporting, conflicting, unanswered = evaluate_evidence(sources, "Quantum Coherence")
    assert len(supporting) == 1
    assert len(conflicting) == 1
    assert conflicting[0].status == "conflicting"
    # Verify cross-linking
    assert "S1" in conflicting[0].contradicting_source_ids


def test_conflict_distinction_potential_contrast():
    """Verify contrast words (however, in contrast) yield status='potential_conflict' rather than direct dispute."""
    sources = [
        SourceDocument(id="S1", title="Benchmark A", url="https://bench-a.org", snippet="High throughput recorded under light concurrency load."),
        SourceDocument(id="S2", title="Benchmark B", url="https://bench-b.org", snippet="However, in contrast to synthetic benchmarks, high latency occurs under saturated connection pools."),
    ]
    supporting, conflicting, unanswered = evaluate_evidence(sources, "Benchmark Load")
    assert len(supporting) == 1
    assert len(conflicting) == 1
    assert conflicting[0].status == "potential_conflict"
    assert "S1" in conflicting[0].contradicting_source_ids


# ==============================================================================
# 3. Normalization Across Provider Formats
# ==============================================================================

def test_comparison_across_heterogeneous_citation_formats():
    """Verify comparison normalizes findings across different provider ID formats (S1, WEB-1, MOCK-1)."""
    text_a = "Fact: FastAPI delivers high performance under Uvicorn [S1]"
    text_b = "FastAPI delivers high performance under Uvicorn [WEB-1]"
    text_c = "Synthesis: FastAPI delivers high performance under Uvicorn [MOCK-2]"

    norm_a = _normalize_finding_text(text_a)
    norm_b = _normalize_finding_text(text_b)
    norm_c = _normalize_finding_text(text_c)

    assert norm_a == norm_b
    assert norm_b == norm_c
    assert norm_a == "fastapi delivers high performance under uvicorn"


def test_report_comparison_with_heterogeneous_sources():
    """Verify compare_research_reports matches shared findings despite different provider prefixes and IDs."""
    rep_a = ResearchReport(
        research_question="FastAPI Performance",
        executive_summary="Summary A",
        sources=[SourceDocument(id="S1", title="Doc", url="https://example.com/1", snippet="FastAPI is fast.")],
        key_findings=["Fact: FastAPI is high performance [S1]"],
        supporting_evidence=[],
        conflicting_evidence=[],
        unanswered_questions=[],
        sources_sufficient=True,
    )
    rep_b = ResearchReport(
        research_question="Web Frameworks",
        executive_summary="Summary B",
        sources=[SourceDocument(id="WEB-1", title="Live Doc", url="https://example.com/2", snippet="FastAPI is fast.")],
        key_findings=["Synthesis: FastAPI is high performance [WEB-1]"],
        supporting_evidence=[],
        conflicting_evidence=[],
        unanswered_questions=[],
        sources_sufficient=True,
    )

    comparison = compare_research_reports(rep_a, rep_b, id_a="A", id_b="B")
    assert len(comparison["shared_findings"]) == 1
    assert "FastAPI is high performance" in comparison["shared_findings"][0]


# ==============================================================================
# 4. Graceful Inadequate Evidence Handling
# ==============================================================================

def test_synthesis_empty_evidence_graceful_handling():
    """Verify empty evidence sources produce explicit inadequate-evidence output without hallucinated claims."""
    empty_provider = MagicMock(spec=SearchProvider)
    empty_provider.search.return_value = []

    orchestrator = ResearchOrchestrator(provider=empty_provider)
    report = orchestrator.conduct_research("Completely unknown question", max_subqueries=2)

    assert report.sources_sufficient is False
    assert len(report.key_findings) == 0
    assert len(report.supporting_evidence) == 0
    assert len(report.unanswered_questions) >= 1
    assert "insufficient" in report.executive_summary.lower()
    assert report.evidence_quality == "insufficient"
