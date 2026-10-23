import html
import os
import re
import urllib.parse
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import httpx

from app.research.state import RetrievalStatus, SourceDocument


class SearchProvider(ABC):
    """Abstract interface for external search providers."""

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> List[SourceDocument]:
        """
        Executes a search query and returns a list of source documents.
        """
        pass


class DeterministicMockSearchProvider(SearchProvider):
    """
    Deterministic, offline mock search provider for unit testing and local development.
    Does NOT use external APIs, paid keys, or internet access.
    Clearly marks all sources as mock data to maintain research integrity.
    """

    def __init__(self, custom_corpus: Optional[Dict[str, List[Dict[str, str]]]] = None):
        # Default mock knowledge base covering diverse topics for testing
        self.corpus = custom_corpus or {
            "fastapi": [
                {
                    "title": "FastAPI Framework Documentation",
                    "url": "https://fastapi.tiangolo.com/tutorial/",
                    "snippet": "FastAPI is a modern, high-performance web framework for building APIs with Python based on standard Python type hints.",
                },
                {
                    "title": "FastAPI Performance Benchmarks",
                    "url": "https://fastapi.tiangolo.com/benchmarks/",
                    "snippet": "Independent TechEmpower benchmarks show FastAPI applications running under Uvicorn provide throughput comparable to NodeJS and Go.",
                },
            ],
            "python": [
                {
                    "title": "Python Official Documentation",
                    "url": "https://docs.python.org/3/",
                    "snippet": "Python is an interpreted, high-level, general-purpose programming language emphasizing code readability with dynamic typing.",
                },
                {
                    "title": "Python GIL and Concurrency",
                    "url": "https://docs.python.org/3/c-api/init.html",
                    "snippet": "In CPython, the global interpreter lock (GIL) prevents multiple native threads from executing Python bytecodes simultaneously in a single process.",
                },
            ],
            "quantum": [
                {
                    "title": "Quantum Computing Roadmap A",
                    "url": "https://example-quantum.org/progress",
                    "snippet": "Laboratory tests indicate fault-tolerant qubits were achieved at room temperature in 2025.",
                },
                {
                    "title": "Quantum Physics Review B",
                    "url": "https://example-physics.org/dispute",
                    "snippet": "Independent laboratories dispute room temperature quantum claims, showing decoherence rates exceeding acceptable error thresholds.",
                },
            ],
        }

    def search(self, query: str, max_results: int = 5) -> List[SourceDocument]:
        if not query or not query.strip():
            return []

        normalized_query = query.lower()
        results: List[SourceDocument] = []
        counter = 1

        for topic, docs in self.corpus.items():
            if topic in normalized_query or any(word in normalized_query for word in topic.split()):
                for doc in docs:
                    if len(results) >= max_results:
                        break
                    results.append(
                        SourceDocument(
                            id=f"MOCK-{counter}",
                            title=doc.get("title", "Untitled Source"),
                            url=doc.get("url", "https://example.com/unknown"),
                            snippet=doc.get("snippet", ""),
                            retrieval_status=RetrievalStatus.SUCCESS,
                            is_mock=True,
                        )
                    )
                    counter += 1

        return results


class DuckDuckGoSearchProvider(SearchProvider):
    """
    Live, zero-cost web search provider utilizing DuckDuckGo's public HTML interface.
    Requires NO paid API key or third-party registration.
    Parses real search results and marks them with is_mock=False.
    """

    SEARCH_URL = "https://html.duckduckgo.com/html/"
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout

    @staticmethod
    def _clean_text(raw_html: str) -> str:
        """Strips HTML tags and unescapes entities."""
        cleaned = re.sub(r"<[^>]+>", "", raw_html)
        return html.unescape(cleaned).strip()

    @staticmethod
    def _extract_canonical_url(raw_href: str) -> str:
        """Extracts direct destination URL from DuckDuckGo redirect wrapper."""
        if "uddg=" in raw_href:
            match = re.search(r"uddg=([^&]+)", raw_href)
            if match:
                return urllib.parse.unquote(match.group(1))
        if raw_href.startswith("//"):
            return f"https:{raw_href}"
        return raw_href

    def search(self, query: str, max_results: int = 5) -> List[SourceDocument]:
        if not query or not query.strip():
            return []

        headers = {
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        data = {"q": query.strip()}

        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                response = client.post(self.SEARCH_URL, data=data, headers=headers)
                response.raise_for_status()
                html_content = response.text

            return self._parse_results(html_content, max_results=max_results)

        except (httpx.TimeoutException, httpx.ConnectTimeout):
            return [
                SourceDocument(
                    id="DDG-ERR",
                    title="DuckDuckGo Search Timeout",
                    url="https://duckduckgo.com",
                    snippet=f"Search request timed out after {self.timeout}s.",
                    retrieval_status=RetrievalStatus.TIMEOUT,
                    is_mock=False,
                )
            ]
        except Exception as err:
            return [
                SourceDocument(
                    id="DDG-ERR",
                    title="DuckDuckGo Search Error",
                    url="https://duckduckgo.com",
                    snippet=f"Failed to retrieve live search results: {str(err)}",
                    retrieval_status=RetrievalStatus.FAILED,
                    is_mock=False,
                )
            ]

    def _parse_results(self, html_content: str, max_results: int = 5) -> List[SourceDocument]:
        """Parses titles, links, and snippets from DuckDuckGo HTML output."""
        results: List[SourceDocument] = []

        # Find result containers or matching links & snippets
        # Matches result title links: <a class="result__a" href="...">Title</a>
        link_matches = list(
            re.finditer(
                r'<a[^>]+class=[\'"][^\'"]*result__a[^\'"]*[\'"][^>]+href=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a>',
                html_content,
                re.DOTALL | re.IGNORECASE,
            )
        )

        # Matches snippets: <a class="result__snippet" ...>Snippet</a>
        snippet_matches = list(
            re.finditer(
                r'<a[^>]+class=[\'"][^\'"]*result__snippet[^\'"]*[\'"][^>]*>(.*?)</a>',
                html_content,
                re.DOTALL | re.IGNORECASE,
            )
        )

        counter = 1
        for idx, link_match in enumerate(link_matches):
            if len(results) >= max_results:
                break

            raw_url = link_match.group(1)
            raw_title = link_match.group(2)
            title = self._clean_text(raw_title)
            url = self._extract_canonical_url(raw_url)

            # Skip DuckDuckGo internal ads or empty URLs
            if not url.startswith("http") or "duckduckgo.com" in url:
                continue

            # Pair with snippet if available
            snippet = ""
            if idx < len(snippet_matches):
                snippet = self._clean_text(snippet_matches[idx].group(1))

            if not snippet:
                snippet = f"Relevant web result retrieved for query from {url}."

            results.append(
                SourceDocument(
                    id=f"WEB-{counter}",
                    title=title or "Web Search Result",
                    url=url,
                    snippet=snippet,
                    retrieval_status=RetrievalStatus.SUCCESS,
                    is_mock=False,
                )
            )
            counter += 1

        return results


class TavilySearchProvider(SearchProvider):
    """
    Search provider adapter for Tavily API (https://tavily.com).
    Activated when TAVILY_API_KEY is configured in the environment.
    """

    API_URL = "https://api.tavily.com/search"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 15.0):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY", "")
        self.timeout = timeout

    def search(self, query: str, max_results: int = 5) -> List[SourceDocument]:
        if not query or not query.strip():
            return []
        if not self.api_key:
            return []

        payload = {
            "api_key": self.api_key,
            "query": query.strip(),
            "max_results": max_results,
            "include_answer": False,
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.post(self.API_URL, json=payload)
                res.raise_for_status()
                data = res.json()

            results: List[SourceDocument] = []
            for idx, item in enumerate(data.get("results", []), 1):
                results.append(
                    SourceDocument(
                        id=f"TAVILY-{idx}",
                        title=item.get("title", "Untitled Web Result"),
                        url=item.get("url", ""),
                        snippet=item.get("content", ""),
                        retrieval_status=RetrievalStatus.SUCCESS,
                        is_mock=False,
                    )
                )
            return results
        except Exception as err:
            return [
                SourceDocument(
                    id="TAVILY-ERR",
                    title="Tavily Search Error",
                    url="https://api.tavily.com",
                    snippet=f"Tavily search request failed: {str(err)}",
                    retrieval_status=RetrievalStatus.FAILED,
                    is_mock=False,
                )
            ]


def get_configured_search_provider() -> SearchProvider:
    """
    Factory function for configuring search providers via environment variables.
    Defaults safely to DeterministicMockSearchProvider for offline stability.
    """
    provider_name = os.getenv("SEARCH_PROVIDER", "mock").lower().strip()

    if provider_name in ("duckduckgo", "ddg", "live", "web"):
        return DuckDuckGoSearchProvider()

    if provider_name == "tavily" and os.getenv("TAVILY_API_KEY"):
        return TavilySearchProvider()

    # Default offline mock provider
    return DeterministicMockSearchProvider()
