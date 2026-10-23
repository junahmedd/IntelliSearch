import html
import ipaddress
import re
import urllib.parse
from typing import Dict, List, Optional, Set, Tuple
from app.research.state import EvidenceClaim, RetrievalStatus, SourceDocument

MAX_SNIPPET_LENGTH = 1000

# Markers that distinguish genuine factual contradictions from nuanced scope/definition contrasts
STRONG_CONTRADICTION_KEYWORDS: Set[str] = {
    "dispute", "disputes", "disputed", "contradict", "contradicts",
    "refuted", "refutes", "false", "debunked", "unproven",
}

POTENTIAL_CONFLICT_KEYWORDS: Set[str] = {
    "however", "on the contrary", "in contrast", "conflict", "conflicts",
    "contrary", "doubt", "controversy",
}

CONFLICT_KEYWORDS: Set[str] = STRONG_CONTRADICTION_KEYWORDS | POTENTIAL_CONFLICT_KEYWORDS


def validate_and_normalize_url(raw_url: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validates URL structure, schemes, and protects against SSRF and malformed targets.
    Enforces HTTP/HTTPS only, blocks private/local IP addresses, and canonicalizes URLs.

    Returns:
        (is_valid, canonical_url, rejection_reason)
    """
    if not raw_url or not isinstance(raw_url, str) or not raw_url.strip():
        return False, None, "URL is empty or missing."

    url = raw_url.strip()

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as e:
        return False, None, f"Malformed URL syntax: {str(e)}"

    # 1. Scheme validation (strictly http or https)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return False, None, f"Unsupported scheme '{scheme}'. Only HTTP and HTTPS are permitted."

    # 2. Netloc / Host validation
    if not parsed.netloc:
        return False, None, "URL is missing network location/host."

    # Reject embedded userinfo (credentials in URL)
    if parsed.username or parsed.password:
        return False, None, "User credentials embedded in URL are prohibited."

    hostname = parsed.hostname
    if not hostname:
        return False, None, "URL is missing a valid hostname."

    hostname_lower = hostname.lower()

    # 3. Guard against SSRF / private networks / loopback
    if hostname_lower in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "::"):
        return False, None, f"Prohibited local loopback address: '{hostname}'."

    if hostname_lower.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
        return False, None, f"Prohibited private/internal domain: '{hostname}'."

    # Check IP addresses (prevent private / internal network scans)
    try:
        ip = ipaddress.ip_address(hostname_lower)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False, None, f"Prohibited non-public IP address (SSRF guard): '{hostname}'."
    except ValueError:
        # Hostname is a domain name, not a raw IP literal
        pass

    # 4. Port validation
    port = parsed.port
    if port is not None and not (1 <= port <= 65535):
        return False, None, f"Invalid port number: {port}"

    # 5. Canonical normalization
    # Construct normalized netloc (strip default ports)
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        netloc = hostname_lower
    elif port is not None:
        netloc = f"{hostname_lower}:{port}"
    else:
        netloc = hostname_lower

    path = parsed.path
    if not path:
        path = "/"
    elif path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Discard fragments, preserve params & query
    canonical_url = urllib.parse.urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))
    return True, canonical_url, None


def sanitize_untrusted_text(raw_text: str, max_length: int = MAX_SNIPPET_LENGTH) -> str:
    """
    Sanitizes external webpage content.
    Treats all incoming text as untrusted raw data:
    - Escapes HTML entities
    - Truncates to prevent memory exhaustion
    - Strips executable-looking script blocks
    """
    if not raw_text:
        return ""

    # Strip script and style blocks
    cleaned = re.sub(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", "", raw_text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<\s*style[^>]*>.*?<\s*/\s*style\s*>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)

    # Escape HTML to prevent XSS / UI injection
    escaped = html.escape(cleaned.strip())

    if len(escaped) > max_length:
        escaped = escaped[:max_length] + " ... [truncated]"

    return escaped


def deduplicate_and_index_sources(
    raw_sources: List[SourceDocument],
    max_sources: int = 10,
) -> List[SourceDocument]:
    """
    Validates URLs, guards against SSRF, deduplicates sources by canonical URL,
    assigns standard sequential IDs (S1, S2, ...), and filters out malformed or unsafe documents.
    """
    seen_urls: Set[str] = set()
    indexed_sources: List[SourceDocument] = []
    counter = 1

    for src in raw_sources:
        if len(indexed_sources) >= max_sources:
            break

        # Validate URL and guard against SSRF
        is_valid, canonical_url, _ = validate_and_normalize_url(src.url)
        if not is_valid or not canonical_url:
            continue

        if canonical_url in seen_urls:
            continue

        seen_urls.add(canonical_url)

        # Sanitize snippet and title as untrusted content
        clean_snippet = sanitize_untrusted_text(src.snippet)
        clean_title = sanitize_untrusted_text(src.title, max_length=150)

        indexed_sources.append(
            SourceDocument(
                id=f"S{counter}",
                title=clean_title,
                url=canonical_url,
                snippet=clean_snippet,
                retrieval_status=src.retrieval_status,
                is_mock=src.is_mock,
            )
        )
        counter += 1

    return indexed_sources


def evaluate_evidence(
    sources: List[SourceDocument],
    question: str,
) -> Tuple[List[EvidenceClaim], List[EvidenceClaim], List[str]]:
    """
    Evaluates source documents to construct verifiable claims linked directly to source IDs.
    Distinguishes supported evidence, conflicting evidence, and unanswered facets.
    Ensures that every generated finding is traceable to verified source documents.

    Returns:
        Tuple of (supporting_evidence, conflicting_evidence, unanswered_questions)
    """
    supporting: List[EvidenceClaim] = []
    conflicting: List[EvidenceClaim] = []
    unanswered: List[str] = []

    successful_sources = [s for s in sources if s.retrieval_status == RetrievalStatus.SUCCESS and s.snippet]

    if not successful_sources:
        unanswered.append(f"No verifiable sources could be retrieved to answer: '{question}'.")
        return supporting, conflicting, unanswered

    # Analyze each source snippet to extract factual claims
    claim_counter = 1
    for src in successful_sources:
        lower_snippet = src.snippet.lower()
        has_strong_conflict = any(kw in lower_snippet for kw in STRONG_CONTRADICTION_KEYWORDS)
        has_potential_conflict = any(kw in lower_snippet for kw in POTENTIAL_CONFLICT_KEYWORDS)

        if has_strong_conflict:
            status = "conflicting"
        elif has_potential_conflict:
            status = "potential_conflict"
        else:
            status = "supported"

        claim = EvidenceClaim(
            claim_id=f"C{claim_counter}",
            claim_text=f"Reported in {src.title}: {src.snippet}",
            supporting_source_ids=[src.id],
            status=status,
        )

        if status in ("conflicting", "potential_conflict"):
            conflicting.append(claim)
        else:
            supporting.append(claim)

        claim_counter += 1

    # Cross-link conflicting claims if mutual contradictions are found
    if conflicting and supporting:
        all_supporting_source_ids = [
            src_id for claim in supporting for src_id in claim.supporting_source_ids
        ]
        for c in conflicting:
            c.contradicting_source_ids = all_supporting_source_ids

    return supporting, conflicting, unanswered
