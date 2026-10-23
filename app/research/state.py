from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class RetrievalStatus(str, Enum):
    """Status of source retrieval."""
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    MALFORMED = "malformed"


class SourceDocument(BaseModel):
    """
    Representation of an external information source.
    Content is treated strictly as untrusted raw text.
    """
    id: str = Field(..., description="Unique source identifier (e.g. S1, S2).")
    title: str = Field(..., description="Document title or headline.")
    url: str = Field(..., description="Source canonical URL.")
    snippet: str = Field(..., description="Extracted factual excerpt or text snippet.")
    retrieval_status: RetrievalStatus = Field(
        default=RetrievalStatus.SUCCESS,
        description="Retrieval outcome status.",
    )
    is_mock: bool = Field(
        default=False,
        description="Whether this source is from a deterministic test mock.",
    )


class EvidenceClaim(BaseModel):
    """
    A specific claim linked directly to source identifiers.
    Preserves strict traceability and flags contradictions.
    """
    claim_id: str = Field(..., description="Unique claim identifier (e.g. C1).")
    claim_text: str = Field(..., description="Factual claim or assertion.")
    supporting_source_ids: List[str] = Field(
        default_factory=list,
        description="List of SourceDocument IDs that directly support this claim.",
    )
    contradicting_source_ids: List[str] = Field(
        default_factory=list,
        description="List of SourceDocument IDs containing conflicting information.",
    )
    status: str = Field(
        default="supported",
        description="'supported', 'conflicting', or 'unverified'",
    )


class SubQuery(BaseModel):
    """A decomposed subquery focusing on a specific facet of the research question."""
    id: str = Field(..., description="Subquery ID (e.g. Q1, Q2).")
    query_text: str = Field(..., description="Focused search query string.")
    intent: str = Field(..., description="Rationale or purpose for this subquery.")


class ResearchReport(BaseModel):
    """
    Comprehensive, evidence-based research report with full source attribution.
    """
    research_question: str = Field(..., description="The user's original research question.")
    executive_summary: str = Field(..., description="High-level synthesis of verified findings.")
    subqueries: List[SubQuery] = Field(
        default_factory=list,
        description="Focused subqueries generated during research planning.",
    )
    sources: List[SourceDocument] = Field(
        default_factory=list,
        description="Complete list of retrieved source documents.",
    )
    key_findings: List[str] = Field(
        default_factory=list,
        description="Bulleted summary of key verified takeaways.",
    )
    supporting_evidence: List[EvidenceClaim] = Field(
        default_factory=list,
        description="Claims with verified links to supporting sources.",
    )
    conflicting_evidence: List[EvidenceClaim] = Field(
        default_factory=list,
        description="Identified contradictions or conflicting reports among sources.",
    )
    unanswered_questions: List[str] = Field(
        default_factory=list,
        description="Aspects of the research question that sources could not answer.",
    )
    sources_sufficient: bool = Field(
        ...,
        description="Whether retrieved evidence was sufficient to address the question.",
    )
    limitations: List[str] = Field(
        default_factory=list,
        description="Methodological limitations or caveats.",
    )
    evidence_quality: str = Field(
        default="moderate",
        description="Explainable evidence quality assessment: 'high', 'moderate', 'low', or 'insufficient'.",
    )
    quality_signals: List[str] = Field(
        default_factory=list,
        description="Explainable quality criteria reflecting relevance, traceability, and conflict status.",
    )


class ResearchRecordSummary(BaseModel):
    """Metadata summary of a saved research record."""
    id: str
    question: str
    status: str
    created_at: str
    sources_count: int
    findings_count: int


class ResearchRecordResponse(BaseModel):
    """Complete saved research record with full report."""
    id: str
    question: str
    status: str
    created_at: str
    updated_at: str
    report: ResearchReport


class ReportComparisonResponse(BaseModel):
    """Deterministic comparison between two saved research reports."""
    id_a: str
    id_b: str
    question_a: str
    question_b: str
    shared_findings: List[str]
    findings_only_in_a: List[str]
    findings_only_in_b: List[str]
    conflicting_claims: List[EvidenceClaim]
    sources_a: List[dict]
    sources_b: List[dict]
    limitations_a: List[str]
    limitations_b: List[str]
    comparison_summary: str

