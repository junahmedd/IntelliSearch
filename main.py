from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.tools.project_inspector import list_project_files
from app.tools.code_search import search_code
from app.agent.orchestrator import InvestigationOrchestrator
from app.agent.state import InvestigationReport
from app.research.orchestrator import ResearchOrchestrator
from app.research.state import (
    ReportComparisonResponse,
    ResearchRecordResponse,
    ResearchReport,
)
from app.research.llm import get_configured_llm_client
from app.research.providers import get_configured_search_provider
from app.research.database import ResearchDatabase
from app.research.comparison import compare_research_reports

# Anchor the permitted workspace strictly to the project root directory
# to prevent arbitrary remote filesystem access.
WORKSPACE_ROOT = Path(__file__).resolve().parent
STATIC_DIR = WORKSPACE_ROOT / "static"

app = FastAPI(
    title="DevPilot AI / IntelliResearch",
    description="Evidence-based AI research and codebase investigation agent API.",
    version="0.1.0",
)

# Mount static asset directory
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ==============================================================================
# Request Models
# ==============================================================================

class InspectRequest(BaseModel):
    subpath: str = Field(
        default=".",
        description="Relative subpath within the project workspace to inspect.",
    )
    max_files: int = Field(
        default=500,
        ge=1,
        le=2000,
        description="Maximum number of files to return.",
    )


class SearchRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description="Text query to search for inside Python source files.",
    )
    subpath: str = Field(
        default=".",
        description="Relative subpath within the project workspace to search.",
    )
    max_results: int = Field(
        default=100,
        ge=1,
        le=500,
        description="Maximum number of search matches to return.",
    )
    case_sensitive: bool = Field(
        default=False,
        description="Whether the search query is case-sensitive.",
    )


class InvestigateRequest(BaseModel):
    bug_description: str = Field(
        ...,
        min_length=3,
        description="Description of the bug, error message, or unexpected behavior to investigate.",
    )
    max_steps: int = Field(
        default=5,
        ge=1,
        le=15,
        description="Maximum reasoning and tool execution steps allowed.",
    )


class ResearchRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=4,
        max_length=500,
        description="The research question to investigate with evidence attribution.",
    )
    max_subqueries: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Maximum number of decomposed subqueries to execute.",
    )
    max_sources: int = Field(
        default=6,
        ge=1,
        le=12,
        description="Maximum number of unique sources to collect.",
    )
    use_llm: bool = Field(
        default=False,
        description="Whether to use configured LLM for synthesis instead of deterministic baseline.",
    )


# ==============================================================================
# Day 1: Foundational Endpoints
# ==============================================================================

@app.get("/")
def read_root():
    """
    Root endpoint: returns a welcome message and current service status.
    """
    return {
        "message": "Welcome to DevPilot AI!",
        "status": "running",
        "version": "0.1.0",
    }


@app.get("/health")
def read_health():
    """
    Health check endpoint: verifies that the server is alive and operational.
    """
    return {"status": "ok"}


# ==============================================================================
# Day 2: Codebase Inspection Tools API
# ==============================================================================

@app.get("/api/tools/inspect")
@app.post("/api/tools/inspect")
def inspect_project_endpoint(request: InspectRequest = InspectRequest()):
    """
    Inspects project directory structure and lists files with metadata.
    Enforces that paths remain strictly within the workspace directory.
    Supports both POST with JSON body and GET with defaults.
    """
    target_path = WORKSPACE_ROOT / request.subpath
    try:
        return list_project_files(
            project_root=target_path,
            max_files=request.max_files,
            base_dir=WORKSPACE_ROOT,
        )
    except (ValueError, FileNotFoundError, NotADirectoryError) as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )


@app.get("/api/tools/search")
def search_code_get_endpoint(
    query: str,
    subpath: str = ".",
    max_results: int = 100,
    case_sensitive: bool = False,
):
    """
    Searches for text in Python files within the workspace via GET query params.
    Enables instant browser URL testing (e.g. /api/tools/search?query=health).
    """
    target_path = WORKSPACE_ROOT / subpath
    try:
        return search_code(
            project_root=target_path,
            query=query,
            max_results=max_results,
            case_sensitive=case_sensitive,
            base_dir=WORKSPACE_ROOT,
        )
    except (ValueError, FileNotFoundError, NotADirectoryError) as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )


@app.post("/api/tools/search")
def search_code_endpoint(request: SearchRequest):
    """
    Searches for text in Python files within the workspace via POST JSON body.
    Enforces that paths remain strictly within the workspace directory.
    """
    target_path = WORKSPACE_ROOT / request.subpath
    try:
        return search_code(
            project_root=target_path,
            query=request.query,
            max_results=request.max_results,
            case_sensitive=request.case_sensitive,
            base_dir=WORKSPACE_ROOT,
        )
    except (ValueError, FileNotFoundError, NotADirectoryError) as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )


# ==============================================================================
# Day 3: Codebase Investigation Agent API
# ==============================================================================

@app.post("/api/agent/investigate", response_model=InvestigationReport)
def investigate_bug_endpoint(request: InvestigateRequest):
    """
    Coordinates a bounded investigation of a reported bug within the project workspace.
    Uses code inspection and text search, strictly confined to the workspace root.
    """
    orchestrator = InvestigationOrchestrator()
    try:
        report = orchestrator.run(
            bug_description=request.bug_description,
            project_root=WORKSPACE_ROOT,
            max_steps=request.max_steps,
            base_dir=WORKSPACE_ROOT,
        )
        return report
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )


# ==============================================================================
# Day 4 & 5: Evidence-Based Research Report Generation Endpoints
# ==============================================================================

@app.post("/api/research/report", response_model=ResearchReport)
def generate_research_report_endpoint(request: ResearchRequest):
    """
    Coordinates an evidence-based research investigation:
    1. Plans subqueries.
    2. Collects and deduplicates sources.
    3. Evaluates evidence and identifies conflicting claims.
    4. Produces a verifiable research report with complete source attribution.
    """
    orchestrator = ResearchOrchestrator(
        provider=get_configured_search_provider(),
        llm_client=get_configured_llm_client(),
    )
    try:
        report = orchestrator.conduct_research(
            question=request.question,
            max_subqueries=request.max_subqueries,
            max_sources=request.max_sources,
            use_llm=request.use_llm,
        )
        return report
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )


@app.get("/api/research/report", response_model=ResearchReport)
def generate_research_report_get_endpoint(
    question: str,
    max_subqueries: int = 3,
    max_sources: int = 6,
    use_llm: bool = False,
):
    """
    GET version for easy browser URL testing:
    e.g. /api/research/report?question=fastapi+performance
    """
    orchestrator = ResearchOrchestrator(
        provider=get_configured_search_provider(),
        llm_client=get_configured_llm_client(),
    )
    try:
        return orchestrator.conduct_research(
            question=question,
            max_subqueries=max_subqueries,
            max_sources=max_sources,
            use_llm=use_llm,
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )


# ==============================================================================
# Day 6: Persistent Research Memory Endpoints
# ==============================================================================

@app.post("/api/research", response_model=ResearchRecordResponse, status_code=status.HTTP_201_CREATED)
def execute_and_save_research_endpoint(request: ResearchRequest):
    """
    Executes an evidence-based research plan and permanently persists the
    resulting report, sources, and metadata to SQLite memory.
    """
    orchestrator = ResearchOrchestrator(
        provider=get_configured_search_provider(),
        llm_client=get_configured_llm_client(),
    )
    db = ResearchDatabase()
    try:
        report = orchestrator.conduct_research(
            question=request.question,
            max_subqueries=request.max_subqueries,
            max_sources=request.max_sources,
            use_llm=request.use_llm,
        )
        research_id = db.save_report(report)
        record = db.get_record(research_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve persisted research record.",
            )
        return record
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )


@app.get("/api/research")
def list_research_history_endpoint(
    limit: int = Query(default=20, ge=1, le=100, description="Max records to return."),
    offset: int = Query(default=0, ge=0, description="Pagination offset."),
):
    """
    Lists previously saved research records with pagination.
    """
    db = ResearchDatabase()
    records, total = db.list_records(limit=limit, offset=offset)
    return {
        "records": records,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/research/search")
def search_research_history_endpoint(
    q: str = Query(..., min_length=2, max_length=100, description="Search term for past research."),
    limit: int = Query(default=20, ge=1, le=50, description="Max results."),
):
    """
    Searches saved research questions and report content.
    """
    db = ResearchDatabase()
    results = db.search_records(query=q, limit=limit)
    return results


@app.get("/api/research/compare", response_model=ReportComparisonResponse)
def compare_research_reports_endpoint(
    id_a: str = Query(..., description="First research record ID."),
    id_b: str = Query(..., description="Second research record ID."),
):
    """
    Deterministically compares two saved research reports.
    Identifies shared findings, unique findings, and conflicting claims.
    """
    db = ResearchDatabase()
    rec_a = db.get_record(id_a)
    if not rec_a:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research record '{id_a}' not found.",
        )

    rec_b = db.get_record(id_b)
    if not rec_b:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research record '{id_b}' not found.",
        )

    comparison = compare_research_reports(
        report_a=rec_a["report"],
        report_b=rec_b["report"],
        id_a=id_a,
        id_b=id_b,
    )
    return comparison


@app.get("/api/research/{research_id}", response_model=ResearchRecordResponse)
def get_saved_research_endpoint(research_id: str):
    """
    Retrieves a specific saved research record and its full structured report.
    """
    db = ResearchDatabase()
    record = db.get_record(research_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research record '{research_id}' not found.",
        )
    return record


@app.delete("/api/research/{research_id}")
def delete_saved_research_endpoint(research_id: str):
    """
    Deletes a saved research record from persistent SQLite memory.
    """
    db = ResearchDatabase()
    deleted = db.delete_record(research_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research record '{research_id}' not found.",
        )
    return {
        "message": "Research record deleted successfully.",
        "id": research_id,
    }


# ==============================================================================
# Day 7: Web UI Endpoints
# ==============================================================================

@app.get("/dashboard", response_class=FileResponse)
@app.get("/ui", response_class=FileResponse)
def get_dashboard():
    """
    Serves the IntelliResearch interactive web dashboard.
    """
    index_file = STATIC_DIR / "index.html"
    if not index_file.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dashboard UI index file not found.",
        )
    return FileResponse(index_file)
