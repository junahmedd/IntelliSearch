import os
from unittest.mock import MagicMock, patch
import httpx
import pytest

from app.research.orchestrator import ResearchOrchestrator
from app.research.providers import (
    DeterministicMockSearchProvider,
    DuckDuckGoSearchProvider,
    SearchProvider,
    TavilySearchProvider,
    get_configured_search_provider,
)
from app.research.state import RetrievalStatus, SourceDocument


SAMPLE_DDG_HTML = """
<!DOCTYPE html>
<html>
<body>
  <div class="result results_links results_links_deep web-result ">
    <div class="result__body links_main links_deep">
      <h2 class="result__title">
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ffastapi.tiangolo.com%2Ftutorial%2F&rut=123">FastAPI Tutorial - User Guide</a>
      </h2>
      <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ffastapi.tiangolo.com%2Ftutorial%2F">FastAPI is a modern, fast (high-performance), web framework for building APIs with Python 3.8+ based on standard Python type hints.</a>
    </div>
  </div>
  <div class="result results_links results_links_deep web-result ">
    <div class="result__body links_main links_deep">
      <h2 class="result__title">
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Ftiangolo%2Ffastapi&rut=456">GitHub - tiangolo/fastapi: FastAPI framework</a>
      </h2>
      <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Ftiangolo%2Ffastapi">FastAPI framework, high performance, easy to learn, fast to code, ready for production.</a>
    </div>
  </div>
</body>
</html>
"""


def test_duckduckgo_provider_parses_html():
    """
    Verify DuckDuckGoSearchProvider successfully extracts real URLs,
    titles, snippets, and marks sources with is_mock=False.
    """
    provider = DuckDuckGoSearchProvider()
    results = provider._parse_results(SAMPLE_DDG_HTML, max_results=5)

    assert len(results) == 2
    first = results[0]
    assert first.title == "FastAPI Tutorial - User Guide"
    assert first.url == "https://fastapi.tiangolo.com/tutorial/"
    assert "FastAPI is a modern, fast" in first.snippet
    assert first.retrieval_status == RetrievalStatus.SUCCESS
    assert first.is_mock is False

    second = results[1]
    assert second.url == "https://github.com/tiangolo/fastapi"
    assert second.is_mock is False


def test_duckduckgo_provider_handles_empty_query():
    """Verify empty or whitespace query returns empty list without making requests."""
    provider = DuckDuckGoSearchProvider()
    assert provider.search("") == []
    assert provider.search("   ") == []


def test_duckduckgo_provider_handles_timeout_mocked():
    """Verify provider returns timeout SourceDocument when HTTP request times out."""
    provider = DuckDuckGoSearchProvider(timeout=5.0)

    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("Read timed out")):
        results = provider.search("python async performance")

    assert len(results) == 1
    assert results[0].retrieval_status == RetrievalStatus.TIMEOUT
    assert "timed out" in results[0].snippet.lower()
    assert results[0].is_mock is False


def test_duckduckgo_provider_handles_network_error_mocked():
    """Verify provider returns failed SourceDocument when HTTP request raises network error."""
    provider = DuckDuckGoSearchProvider()

    with patch("httpx.Client.post", side_effect=httpx.ConnectError("Failed to resolve host")):
        results = provider.search("python async performance")

    assert len(results) == 1
    assert results[0].retrieval_status == RetrievalStatus.FAILED
    assert "Failed to retrieve" in results[0].snippet


def test_tavily_provider_parses_json_mocked():
    """Verify TavilySearchProvider parses API response correctly."""
    provider = TavilySearchProvider(api_key="test-key-tavily")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {
                "title": "Tavily Real Search Result",
                "url": "https://example.org/tavily-result",
                "content": "Real-time AI research source content.",
            }
        ]
    }

    with patch("httpx.Client.post", return_value=mock_resp):
        results = provider.search("quantum teleportation", max_results=3)

    assert len(results) == 1
    assert results[0].title == "Tavily Real Search Result"
    assert results[0].url == "https://example.org/tavily-result"
    assert results[0].snippet == "Real-time AI research source content."
    assert results[0].is_mock is False


def test_tavily_provider_missing_api_key():
    """Verify Tavily returns empty list if no API key is provided."""
    provider = TavilySearchProvider(api_key="")
    assert provider.search("test query") == []


def test_search_provider_factory_default():
    """Verify factory defaults to DeterministicMockSearchProvider when SEARCH_PROVIDER is unset."""
    with patch.dict(os.environ, {}, clear=True):
        provider = get_configured_search_provider()
        assert isinstance(provider, DeterministicMockSearchProvider)


def test_search_provider_factory_duckduckgo():
    """Verify factory returns DuckDuckGoSearchProvider when SEARCH_PROVIDER=duckduckgo."""
    with patch.dict(os.environ, {"SEARCH_PROVIDER": "duckduckgo"}, clear=True):
        provider = get_configured_search_provider()
        assert isinstance(provider, DuckDuckGoSearchProvider)


def test_search_provider_factory_tavily():
    """Verify factory returns TavilySearchProvider when SEARCH_PROVIDER=tavily and key is set."""
    with patch.dict(os.environ, {"SEARCH_PROVIDER": "tavily", "TAVILY_API_KEY": "dummy-key"}, clear=True):
        provider = get_configured_search_provider()
        assert isinstance(provider, TavilySearchProvider)


def test_orchestrator_with_real_provider_mocked():
    """
    Verify ResearchOrchestrator generates report with real sources (is_mock=False)
    and does NOT claim to be an offline mock in limitations.
    """
    mock_real_provider = MagicMock(spec=SearchProvider)
    mock_real_provider.search.return_value = [
        SourceDocument(
            id="WEB-1",
            title="Real Web Documentation",
            url="https://docs.realdomain.org/guide",
            snippet="Real-world benchmark indicates 2x latency reduction.",
            retrieval_status=RetrievalStatus.SUCCESS,
            is_mock=False,
        )
    ]

    orchestrator = ResearchOrchestrator(provider=mock_real_provider)
    report = orchestrator.conduct_research(
        question="What is the real latency impact?",
        max_subqueries=1,
        max_sources=2,
    )

    assert report.sources_sufficient is True
    assert len(report.sources) >= 1
    assert report.sources[0].is_mock is False
    assert report.sources[0].url == "https://docs.realdomain.org/guide"

    # Verify limitations notice does NOT say mock provider
    limitations_text = " ".join(report.limitations)
    assert "offline deterministic mock provider" not in limitations_text
    assert "synthesized from live external web search results" in limitations_text
