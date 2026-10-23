import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.research.evaluator import (
    deduplicate_and_index_sources,
    evaluate_evidence,
    sanitize_untrusted_text,
)
from app.research.orchestrator import ResearchOrchestrator
from app.research.planner import plan_research
from app.research.providers import DeterministicMockSearchProvider, SearchProvider
from app.research.state import RetrievalStatus, SourceDocument
from main import app

client = TestClient(app)


# ==========================================
# 1. Research Planning Tests
# ==========================================

def test_plan_research_valid():
    subqueries = plan_research("What is FastAPI and how does it perform?", max_subqueries=3)
    assert len(subqueries) <= 3
    assert len(subqueries) >= 1
    assert subqueries[0].id == "Q1"
    assert "FastAPI" in subqueries[0].query_text


def test_plan_research_invalid():
    with pytest.raises(ValueError, match="cannot be empty"):
        plan_research("")

    with pytest.raises(ValueError, match="too short"):
        plan_research("hi")


def test_plan_research_max_subqueries():
    subqueries = plan_research("Explain Python memory management and garbage collection in detail", max_subqueries=2)
    assert len(subqueries) <= 2


# ==========================================
# 2. Source Sanitization & Deduplication
# ==========================================

def test_sanitize_untrusted_text():
    dirty = "<script>alert('pwned')</script>Normal text with <b>HTML</b> & special chars."
    sanitized = sanitize_untrusted_text(dirty)
    assert "<script>" not in sanitized
    assert "alert('pwned')" not in sanitized
    assert "&lt;b&gt;HTML&lt;/b&gt;" in sanitized or "Normal text" in sanitized


def test_deduplicate_and_index_sources():
    raw_sources = [
        SourceDocument(id="1", title="Doc 1", url="https://example.com/a", snippet="First snippet"),
        SourceDocument(id="2", title="Doc 1 Dup", url="https://example.com/a/", snippet="Duplicate snippet"),
        SourceDocument(id="3", title="Doc 2", url="https://example.com/b", snippet="Second snippet"),
        SourceDocument(id="4", title="Invalid", url="ftp://invalid-scheme", snippet="Bad"),
    ]

    indexed = deduplicate_and_index_sources(raw_sources, max_sources=5)
    assert len(indexed) == 2
    assert indexed[0].id == "S1"
    assert indexed[1].id == "S2"
    assert indexed[0].url == "https://example.com/a"
    assert indexed[1].url == "https://example.com/b"


# ==========================================
# 3. Evidence Evaluation & Attribution
# ==========================================

def test_evaluate_evidence_supported():
    sources = [
        SourceDocument(
            id="S1",
            title="FastAPI Docs",
            url="https://fastapi.tiangolo.com",
            snippet="FastAPI is a modern web framework for Python.",
            retrieval_status=RetrievalStatus.SUCCESS,
        )
    ]
    supporting, conflicting, unanswered = evaluate_evidence(sources, "FastAPI")
    assert len(supporting) == 1
    assert len(conflicting) == 0
    assert len(unanswered) == 0
    assert supporting[0].supporting_source_ids == ["S1"]
    assert supporting[0].status == "supported"


def test_evaluate_evidence_conflicting():
    sources = [
        SourceDocument(
            id="S1",
            title="Claim Source",
            url="https://source1.com",
            snippet="The experimental result is confirmed.",
            retrieval_status=RetrievalStatus.SUCCESS,
        ),
        SourceDocument(
            id="S2",
            title="Dispute Source",
            url="https://source2.com",
            snippet="Independent teams dispute and contradict the experimental result.",
            retrieval_status=RetrievalStatus.SUCCESS,
        ),
    ]
    supporting, conflicting, unanswered = evaluate_evidence(sources, "Experiment")
    assert len(supporting) == 1
    assert len(conflicting) == 1
    assert conflicting[0].status == "conflicting"
    assert "S1" in conflicting[0].contradicting_source_ids


def test_evaluate_evidence_empty_sources():
    supporting, conflicting, unanswered = evaluate_evidence([], "Unknown Question")
    assert len(supporting) == 0
    assert len(conflicting) == 0
    assert len(unanswered) == 1
    assert "No verifiable sources" in unanswered[0]


# ==========================================
# 4. Research Orchestrator Tests
# ==========================================

def test_orchestrator_successful_report():
    orchestrator = ResearchOrchestrator(DeterministicMockSearchProvider())
    report = orchestrator.conduct_research("What is FastAPI?", max_subqueries=2, max_sources=4)

    assert report.research_question == "What is FastAPI?"
    assert report.sources_sufficient is True
    assert len(report.sources) >= 1
    assert len(report.key_findings) >= 1
    # Traceability check: Every key finding has a [S...] tag
    assert any("[S1]" in finding for finding in report.key_findings)


def test_orchestrator_conflicting_report():
    orchestrator = ResearchOrchestrator(DeterministicMockSearchProvider())
    report = orchestrator.conduct_research("Room temperature quantum computing claims", max_subqueries=2)

    assert len(report.conflicting_evidence) >= 1
    assert any("Contradictory evidence detected" in lim for lim in report.limitations)


def test_orchestrator_insufficient_sources():
    orchestrator = ResearchOrchestrator(DeterministicMockSearchProvider())
    # Question not in mock corpus
    report = orchestrator.conduct_research("Completely unknown celestial anomaly 9999", max_subqueries=2)

    assert report.sources_sufficient is False
    assert len(report.key_findings) == 0
    assert len(report.unanswered_questions) >= 1
    assert "insufficient" in report.executive_summary.lower()


def test_orchestrator_handles_provider_error():
    mock_provider = MagicMock(spec=SearchProvider)
    mock_provider.search.side_effect = TimeoutError("Connection timed out to search gateway")

    orchestrator = ResearchOrchestrator(mock_provider)
    report = orchestrator.conduct_research("Any valid question", max_subqueries=2)

    assert report.sources_sufficient is False
    assert any(s.retrieval_status == RetrievalStatus.FAILED for s in report.sources)


# ==========================================
# 5. API Endpoint Tests
# ==========================================

def test_api_research_report_post():
    response = client.post(
        "/api/research/report",
        json={"question": "What is Python and its GIL?", "max_subqueries": 2, "max_sources": 3},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["research_question"] == "What is Python and its GIL?"
    assert "executive_summary" in data
    assert "sources" in data
    assert "key_findings" in data
    assert isinstance(data["sources_sufficient"], bool)


def test_api_research_report_get():
    response = client.get("/api/research/report?question=fastapi+framework&max_sources=2")
    assert response.status_code == 200
    data = response.json()
    assert data["sources_sufficient"] is True


def test_api_research_report_validation_error():
    # Question too short (< 4 chars)
    response = client.post("/api/research/report", json={"question": "hi"})
    assert response.status_code == 422
