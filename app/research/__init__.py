"""IntelliResearch research agent package."""

from app.research.comparison import compare_research_reports
from app.research.database import ResearchDatabase
from app.research.evaluator import (
    deduplicate_and_index_sources,
    evaluate_evidence,
    validate_and_normalize_url,
)
from app.research.grounding import GroundingValidationError, validate_and_ground_report
from app.research.llm import (
    BaseLLMClient,
    MockLLMClient,
    OpenAICompatibleLLMClient,
    get_configured_llm_client,
    redact_secret,
)
from app.research.orchestrator import ResearchOrchestrator
from app.research.planner import plan_research
from app.research.providers import (
    DeterministicMockSearchProvider,
    DuckDuckGoSearchProvider,
    SearchProvider,
    TavilySearchProvider,
    get_configured_search_provider,
)
from app.research.state import (
    EvidenceClaim,
    ReportComparisonResponse,
    ResearchRecordResponse,
    ResearchRecordSummary,
    ResearchReport,
    RetrievalStatus,
    SourceDocument,
    SubQuery,
)

__all__ = [
    "EvidenceClaim",
    "ResearchReport",
    "ResearchRecordSummary",
    "ResearchRecordResponse",
    "ReportComparisonResponse",
    "RetrievalStatus",
    "SourceDocument",
    "SubQuery",
    "SearchProvider",
    "DeterministicMockSearchProvider",
    "DuckDuckGoSearchProvider",
    "TavilySearchProvider",
    "get_configured_search_provider",
    "BaseLLMClient",
    "MockLLMClient",
    "OpenAICompatibleLLMClient",
    "get_configured_llm_client",
    "redact_secret",
    "GroundingValidationError",
    "validate_and_ground_report",
    "plan_research",
    "deduplicate_and_index_sources",
    "evaluate_evidence",
    "validate_and_normalize_url",
    "ResearchOrchestrator",
    "ResearchDatabase",
    "compare_research_reports",
]
