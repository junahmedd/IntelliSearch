import pytest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.agent.state import ToolName, ToolObservation
from app.agent.orchestrator import (
    DeterministicDecisionPolicy,
    InvestigationOrchestrator,
    extract_candidate_search_terms,
)
from main import app

client = TestClient(app)


@pytest.fixture
def agent_sample_project(tmp_path: Path):
    """Creates a temporary workspace with specific bug-related code."""
    proj = tmp_path / "target_repo"
    proj.mkdir()

    # Create auth module
    auth_file = proj / "auth.py"
    auth_file.write_text(
        "def authenticate_user(token):\n"
        "    if not token:\n"
        "        raise ValueError('Invalid token provided')\n"
        "    return {'user_id': 123}\n",
        encoding="utf-8",
    )

    # Create service module
    service_file = proj / "service.py"
    service_file.write_text(
        "from auth import authenticate_user\n\n"
        "def process_order(token):\n"
        "    user = authenticate_user(token)\n"
        "    return user\n",
        encoding="utf-8",
    )

    return proj


# ==========================================
# 1. Term Extraction & Policy Unit Tests
# ==========================================

def test_extract_candidate_search_terms():
    desc = "User report: authenticate_user() failed with 'Invalid token provided' in auth.py"
    terms = extract_candidate_search_terms(desc)
    assert "Invalid token provided" in terms
    assert "authenticate_user" in terms
    assert "auth" in terms


def test_extract_candidate_search_terms_empty():
    assert extract_candidate_search_terms("") == []


def test_decision_policy_step_progression():
    policy = DeterministicDecisionPolicy("Error in authenticate_user when token is None")
    
    # Step 1: Must be inspect_project
    thought1, tool1, params1 = policy.decide_next_action(step_number=1, max_steps=5)
    assert tool1 == ToolName.INSPECT_PROJECT
    assert params1 == {}

    # Step 2: Must search for the first candidate term
    thought2, tool2, params2 = policy.decide_next_action(step_number=2, max_steps=5)
    assert tool2 == ToolName.SEARCH_CODE
    assert "query" in params2
    assert params2["query"] == "authenticate_user"

    # Step progression does not repeat the same search query
    searched_queries = [params2["query"]]
    for step in range(3, 6):
        _, tool, params = policy.decide_next_action(step_number=step, max_steps=5)
        if tool == ToolName.SEARCH_CODE:
            assert params["query"] not in searched_queries
            searched_queries.append(params["query"])


# ==========================================
# 2. Orchestrator Unit & Integration Tests
# ==========================================

def test_orchestrator_successful_investigation(agent_sample_project: Path):
    orchestrator = InvestigationOrchestrator()
    report = orchestrator.run(
        bug_description="authenticate_user fails with 'Invalid token provided'",
        project_root=agent_sample_project,
        max_steps=5,
        base_dir=agent_sample_project,
    )

    assert report.status == "completed"
    assert report.total_steps >= 2
    assert len(report.observed_evidence) >= 1

    # Check evidence structure
    ev = report.observed_evidence[0]
    assert ev.file in ["auth.py", "service.py"]
    assert ev.line_number > 0
    assert "def authenticate_user" in ev.line_content or "Invalid token provided" in ev.line_content

    # Strict separation: evidence present, hypothesis clearly labeled as hypothesis
    assert report.suspected_root_cause is not None
    assert "Candidate symbols" in report.suspected_root_cause
    assert "manual verification" in report.suspected_root_cause


def test_orchestrator_no_matches(agent_sample_project: Path):
    orchestrator = InvestigationOrchestrator()
    report = orchestrator.run(
        bug_description="UnknownModule.missing_function crashed",
        project_root=agent_sample_project,
        max_steps=5,
        base_dir=agent_sample_project,
    )

    assert report.status == "completed"
    assert len(report.observed_evidence) == 0
    assert "No direct source code matches" in report.suspected_root_cause


def test_orchestrator_invalid_inputs(agent_sample_project: Path):
    orchestrator = InvestigationOrchestrator()
    with pytest.raises(ValueError, match="Bug description cannot be empty"):
        orchestrator.run("", project_root=agent_sample_project)

    with pytest.raises(ValueError, match="max_steps must be at least 1"):
        orchestrator.run("Error", project_root=agent_sample_project, max_steps=0)


def test_orchestrator_step_limit_enforced(agent_sample_project: Path):
    orchestrator = InvestigationOrchestrator()
    # With max_steps=1, it should only perform the initial inspect_project step
    report = orchestrator.run(
        bug_description="Error in authenticate_user and process_order",
        project_root=agent_sample_project,
        max_steps=1,
        base_dir=agent_sample_project,
    )

    assert report.status == "max_steps_reached"
    assert report.total_steps == 1
    assert report.steps_taken[0].action == ToolName.INSPECT_PROJECT.value


def test_orchestrator_handles_tool_failure(agent_sample_project: Path):
    orchestrator = InvestigationOrchestrator()
    # Force search_code to raise an error
    with patch("app.agent.orchestrator.search_code", side_effect=PermissionError("Mocked access error")):
        report = orchestrator.run(
            bug_description="authenticate_user issue",
            project_root=agent_sample_project,
            max_steps=3,
            base_dir=agent_sample_project,
        )

        assert report.total_steps >= 2
        # Verify the error was safely captured in observation
        search_steps = [s for s in report.steps_taken if s.action == ToolName.SEARCH_CODE.value]
        assert len(search_steps) >= 1
        assert search_steps[0].observation.success is False
        assert "Mocked access error" in search_steps[0].observation.error


# ==========================================
# 3. FastAPI Endpoint Tests
# ==========================================

def test_api_investigate_endpoint():
    response = client.post(
        "/api/agent/investigate",
        json={"bug_description": "read_health returns ok status", "max_steps": 3},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["completed", "max_steps_reached"]
    assert "observed_evidence" in data
    assert "suspected_root_cause" in data
    assert "summary" in data
    assert data["total_steps"] >= 1


def test_api_investigate_endpoint_validation_errors():
    # Empty description (< 3 chars)
    response = client.post("/api/agent/investigate", json={"bug_description": "ab"})
    assert response.status_code == 422

    # max_steps out of range (ge=1, le=15)
    response = client.post(
        "/api/agent/investigate",
        json={"bug_description": "Valid bug", "max_steps": 0},
    )
    assert response.status_code == 422
