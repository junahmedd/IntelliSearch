import pytest
from app.research.evaluator import (
    deduplicate_and_index_sources,
    evaluate_evidence,
    validate_and_normalize_url,
)
from app.research.orchestrator import ResearchOrchestrator
from app.research.database import ResearchDatabase
from app.research.state import RetrievalStatus, SourceDocument


# ==============================================================================
# 1. URL Validation & SSRF Guard Tests
# ==============================================================================

def test_validate_and_normalize_url_valid():
    """Verify standard HTTP and HTTPS web URLs pass validation and normalize."""
    is_valid, url, err = validate_and_normalize_url("https://fastapi.tiangolo.com/tutorial/")
    assert is_valid is True
    assert url == "https://fastapi.tiangolo.com/tutorial"
    assert err is None

    # Test query preservation
    is_valid, url, err = validate_and_normalize_url("http://example.org:80/search?q=python#fragment")
    assert is_valid is True
    assert url == "http://example.org/search?q=python"  # Port 80 stripped, fragment dropped


def test_validate_and_normalize_url_rejects_unsafe_schemes():
    """Verify non-HTTP schemes are strictly blocked."""
    unsafe_urls = [
        "file:///etc/passwd",
        "file://C:/Windows/win.ini",
        "javascript:alert('xss')",
        "ftp://ftp.example.org/data.csv",
        "data:text/html;base64,PHNjcmlwdD4=",
        "gopher://evil.com/",
    ]
    for target in unsafe_urls:
        is_valid, url, err = validate_and_normalize_url(target)
        assert is_valid is False
        assert url is None
        assert "Unsupported scheme" in err


def test_validate_and_normalize_url_ssrf_loopback():
    """Verify loopback addresses are blocked to prevent local host SSRF."""
    loopbacks = [
        "http://localhost/admin",
        "http://127.0.0.1:8080/metrics",
        "http://0.0.0.0:5000/",
        "http://[::1]:9090/",
        "http://service.localhost/api",
    ]
    for target in loopbacks:
        is_valid, url, err = validate_and_normalize_url(target)
        assert is_valid is False
        assert url is None
        assert "loopback" in err.lower() or "prohibited" in err.lower()


def test_validate_and_normalize_url_ssrf_private_networks():
    """Verify RFC 1918 private IPv4 subnets are blocked."""
    private_ips = [
        "http://10.0.0.1/status",
        "http://10.255.0.1:8000/internal",
        "http://172.16.0.5/conf",
        "http://172.31.255.255/db",
        "http://192.168.1.1/router",
        "http://192.168.0.100:3000/",
    ]
    for target in private_ips:
        is_valid, url, err = validate_and_normalize_url(target)
        assert is_valid is False
        assert url is None
        assert "SSRF guard" in err


def test_validate_and_normalize_url_ssrf_aws_metadata():
    """Verify link-local cloud metadata endpoints (169.254.169.254) are blocked."""
    is_valid, url, err = validate_and_normalize_url("http://169.254.169.254/latest/meta-data/")
    assert is_valid is False
    assert url is None
    assert "SSRF guard" in err


def test_validate_and_normalize_url_rejects_credentials():
    """Verify user credentials embedded in URLs are blocked."""
    is_valid, url, err = validate_and_normalize_url("https://admin:secret123@example.com/api")
    assert is_valid is False
    assert "User credentials" in err


# ==============================================================================
# 2. Source Deduplication & Quality Tests
# ==============================================================================

def test_deduplicate_and_index_sources_drops_unsafe_and_duplicates():
    """Verify deduplicate_and_index_sources discards unsafe URLs and canonical duplicates."""
    raw = [
        SourceDocument(id="RAW-1", title="FastAPI Docs", url="https://fastapi.tiangolo.com/tutorial/", snippet="Guide 1"),
        # Canonical duplicate with trailing slash difference and port 443
        SourceDocument(id="RAW-2", title="FastAPI Docs Dup", url="https://fastapi.tiangolo.com:443/tutorial", snippet="Guide 2"),
        # SSRF attempt
        SourceDocument(id="RAW-3", title="Internal Admin", url="http://192.168.1.1/admin", snippet="Secrets"),
        # Malformed scheme
        SourceDocument(id="RAW-4", title="Local File", url="file:///etc/hosts", snippet="Hosts file"),
        # Valid second source
        SourceDocument(id="RAW-5", title="FastAPI Benchmarks", url="https://fastapi.tiangolo.com/benchmarks", snippet="Benchmarks"),
    ]

    indexed = deduplicate_and_index_sources(raw, max_sources=5)
    assert len(indexed) == 2
    assert indexed[0].id == "S1"
    assert indexed[0].url == "https://fastapi.tiangolo.com/tutorial"
    assert indexed[1].id == "S2"
    assert indexed[1].url == "https://fastapi.tiangolo.com/benchmarks"


# ==============================================================================
# 3. Evidence Traceability & Quality Signals Tests
# ==============================================================================

def test_evidence_traceability_and_quality_signals():
    """Verify orchestrator attaches explainable quality signals and preserves claim traceability."""
    orchestrator = ResearchOrchestrator()
    report = orchestrator.conduct_research(
        question="What is FastAPI performance and GIL concurrency?",
        max_subqueries=2,
        max_sources=4,
    )

    assert report.sources_sufficient is True
    assert report.evidence_quality in ("high", "moderate")
    assert len(report.quality_signals) >= 3

    # Check signal strings are explainable
    signals_text = " ".join(report.quality_signals)
    assert "Provenance:" in signals_text
    assert "Source Coverage:" in signals_text
    assert "Claim Traceability:" in signals_text

    # Every key finding must cite source IDs (e.g. [S1])
    for finding in report.key_findings:
        assert "[" in finding and "]" in finding


def test_insufficient_evidence_quality_signal():
    """Verify report with zero sources sets evidence_quality to 'insufficient'."""
    from unittest.mock import MagicMock
    from app.research.providers import SearchProvider

    empty_provider = MagicMock(spec=SearchProvider)
    empty_provider.search.return_value = []

    orchestrator = ResearchOrchestrator(provider=empty_provider)
    report = orchestrator.conduct_research("Completely unknown exotic concept")

    assert report.sources_sufficient is False
    assert report.evidence_quality == "insufficient"
    assert any("Traceability: No verifiable findings" in s for s in report.quality_signals)


def test_report_persistence_preserves_quality_and_traceability():
    """Integration test confirming quality signals and citations survive SQLite storage roundtrip."""
    orchestrator = ResearchOrchestrator()
    db = ResearchDatabase()

    report = orchestrator.conduct_research("FastAPI async architecture")
    rec_id = db.save_report(report)

    record = db.get_record(rec_id)
    assert record is not None
    loaded_report = record["report"]

    assert loaded_report.evidence_quality == report.evidence_quality
    assert loaded_report.quality_signals == report.quality_signals
    assert len(loaded_report.key_findings) == len(report.key_findings)
    assert loaded_report.sources[0].url == report.sources[0].url
