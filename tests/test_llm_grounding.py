import json
import pytest
from unittest.mock import MagicMock, patch
import httpx

from app.research.grounding import validate_and_ground_report
from app.research.llm import (
    MockLLMClient,
    OpenAICompatibleLLMClient,
    get_configured_llm_client,
    redact_secret,
)
from app.research.orchestrator import ResearchOrchestrator
from app.research.providers import DeterministicMockSearchProvider
from app.research.state import RetrievalStatus, SourceDocument, SubQuery


@pytest.fixture
def sample_sources():
    return [
        SourceDocument(
            id="S1",
            title="FastAPI Overview",
            url="https://fastapi.tiangolo.com",
            snippet="FastAPI is a modern web framework for Python.",
            retrieval_status=RetrievalStatus.SUCCESS,
        ),
        SourceDocument(
            id="S2",
            title="Python Concurrency",
            url="https://docs.python.org",
            snippet="CPython uses a GIL for memory safety.",
            retrieval_status=RetrievalStatus.SUCCESS,
        ),
    ]


@pytest.fixture
def sample_subqueries():
    return [
        SubQuery(id="Q1", query_text="What is FastAPI?", intent="Overview"),
    ]


# ==============================================================================
# 1. Grounding & Hallucination Defense Tests
# ==============================================================================

def test_grounding_valid_model_output(sample_sources, sample_subqueries):
    model_output = {
        "executive_summary": "FastAPI is a fast web framework.",
        "key_findings": ["FastAPI uses standard Python type hints [S1]."],
        "supporting_evidence": [
            {
                "claim_text": "FastAPI is built on Python type hints.",
                "supporting_source_ids": ["S1"],
            }
        ],
        "conflicting_evidence": [],
        "unanswered_questions": [],
        "limitations": [],
    }

    report = validate_and_ground_report(
        question="What is FastAPI?",
        subqueries=sample_subqueries,
        sources=sample_sources,
        model_output=model_output,
    )

    assert report.sources_sufficient is True
    assert len(report.supporting_evidence) == 1
    assert report.supporting_evidence[0].status == "supported"
    assert report.supporting_evidence[0].supporting_source_ids == ["S1"]


def test_grounding_rejects_unknown_source_ids(sample_sources, sample_subqueries):
    # Model hallucinated source IDs "S99" and "FAKE_SRC"
    model_output = {
        "executive_summary": "Unverified claims summary.",
        "key_findings": ["Hallucinated claim [S99]."],
        "supporting_evidence": [
            {
                "claim_text": "Invented claim with fake source.",
                "supporting_source_ids": ["S99", "FAKE_SRC"],
            }
        ],
        "conflicting_evidence": [],
        "unanswered_questions": [],
        "limitations": [],
    }

    report = validate_and_ground_report(
        question="What is FastAPI?",
        subqueries=sample_subqueries,
        sources=sample_sources,
        model_output=model_output,
    )

    # Unknown source IDs are stripped
    assert len(report.supporting_evidence) == 1
    claim = report.supporting_evidence[0]
    assert "S99" not in claim.supporting_source_ids
    assert "FAKE_SRC" not in claim.supporting_source_ids
    # Because valid supporting sources were absent, claim status is marked 'unverified'
    assert claim.status == "unverified"
    assert report.sources_sufficient is False


def test_grounding_empty_sources(sample_subqueries):
    model_output = {
        "executive_summary": "Cannot answer without sources.",
        "key_findings": [],
        "supporting_evidence": [],
        "conflicting_evidence": [],
        "unanswered_questions": ["All questions unanswered."],
        "limitations": [],
    }

    report = validate_and_ground_report(
        question="What is FastAPI?",
        subqueries=sample_subqueries,
        sources=[],
        model_output=model_output,
    )

    assert report.sources_sufficient is False
    assert any("insufficient" in u.lower() for u in report.unanswered_questions)


# ==============================================================================
# 2. Secret Redaction & Security Tests
# ==============================================================================

def test_redact_secret_removes_api_key():
    api_key = "gsk_secret_1234567890abcdef"
    error_msg = f"Failed to connect using key {api_key} at endpoint."
    redacted = redact_secret(error_msg, api_key)
    assert api_key not in redacted
    assert "***REDACTED***" in redacted


def test_redact_secret_handles_none_and_empty():
    text = "Normal error message."
    assert redact_secret(text, None) == text
    assert redact_secret(text, "") == text


# ==============================================================================
# 3. Provider Adapter & Error Handling Tests (Offline Mocks)
# ==============================================================================

def test_openai_adapter_missing_api_key_for_remote_provider():
    client = OpenAICompatibleLLMClient(
        api_key="",
        base_url="https://api.groq.com/openai/v1",
    )
    with pytest.raises(ValueError, match="API key is required"):
        client.generate_report_payload("Question", [])


def test_openai_adapter_allows_local_ollama_without_key():
    client = OpenAICompatibleLLMClient(
        api_key="",
        base_url="http://localhost:11434/v1",
    )
    # Does not raise ValueError on initialization for local endpoints
    assert client.base_url == "http://localhost:11434/v1"


def test_openai_adapter_handles_timeout():
    client = OpenAICompatibleLLMClient(
        api_key="dummy_key",
        base_url="https://api.groq.com/openai/v1",
        timeout=1.0,
    )
    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("Mocked timeout")):
        with pytest.raises(RuntimeError, match="timed out"):
            client.generate_report_payload("Question", [])


def test_openai_adapter_handles_rate_limit_429():
    client = OpenAICompatibleLLMClient(
        api_key="dummy_key_123",
        base_url="https://api.groq.com/openai/v1",
    )
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.text = "Rate limit reached for dummy_key_123"

    with patch(
        "httpx.Client.post",
        side_effect=httpx.HTTPStatusError("Rate Limit", request=MagicMock(), response=mock_response),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            client.generate_report_payload("Question", [])

        err_text = str(exc_info.value)
        assert "rate limit exceeded" in err_text.lower()
        # Verify secret was redacted even from error output
        assert "dummy_key_123" not in err_text


# ==============================================================================
# 4. Orchestrator Integration & Fallback Tests
# ==============================================================================

def test_orchestrator_with_mock_llm():
    mock_llm = MockLLMClient()
    orchestrator = ResearchOrchestrator(
        provider=DeterministicMockSearchProvider(),
        llm_client=mock_llm,
    )

    report = orchestrator.conduct_research(
        question="What is FastAPI?",
        max_subqueries=2,
        use_llm=True,
    )

    assert report.sources_sufficient is True
    assert len(report.supporting_evidence) >= 1
    # Check that source attribution exists
    assert report.supporting_evidence[0].supporting_source_ids[0].startswith("S")


def test_orchestrator_fallback_when_llm_fails():
    failing_llm = MagicMock()
    failing_llm.generate_report_payload.side_effect = RuntimeError("Mocked LLM crash")

    orchestrator = ResearchOrchestrator(
        provider=DeterministicMockSearchProvider(),
        llm_client=failing_llm,
    )

    # When fallback_to_deterministic=True (default), does not crash; falls back gracefully
    report = orchestrator.conduct_research(
        question="What is FastAPI?",
        max_subqueries=2,
        use_llm=True,
        fallback_to_deterministic=True,
    )

    assert report.sources_sufficient is True
    assert any("Reverted to deterministic evaluation fallback" in lim for lim in report.limitations)


def test_get_configured_llm_client_default():
    # When LLM_PROVIDER is unset or "mock", returns MockLLMClient
    with patch.dict("os.environ", {"LLM_PROVIDER": "mock"}):
        client = get_configured_llm_client()
        assert isinstance(client, MockLLMClient)
