from pathlib import Path
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from app.tools.project_inspector import list_project_files
from app.tools.code_search import search_code
from app.agent.orchestrator import InvestigationOrchestrator
from app.agent.state import InvestigationReport

# Anchor the permitted workspace strictly to the project root directory
# to prevent arbitrary remote filesystem access.
WORKSPACE_ROOT = Path(__file__).resolve().parent

app = FastAPI(
    title="DevPilot AI",
    description="An AI software engineering agent API for investigating bugs, searching codebases, and running verification tests.",
    version="0.1.0",
)


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
