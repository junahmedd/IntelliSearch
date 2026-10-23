from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.research.comparison import compare_research_reports
from app.research.database import ResearchDatabase
from app.research.orchestrator import ResearchOrchestrator
from app.research.providers import DeterministicMockSearchProvider
from app.research.state import EvidenceClaim, ResearchReport, SourceDocument, SubQuery
from main import app

client = TestClient(app)


@pytest.fixture
def temp_db(tmp_path: Path):
    """Provides an isolated SQLite database for unit tests."""
    db_file = tmp_path / "test_research.db"
    return ResearchDatabase(db_path=db_file)


@pytest.fixture
def sample_report():
    return ResearchReport(
        research_question="What is FastAPI?",
        executive_summary="FastAPI is a modern web framework.",
        subqueries=[SubQuery(id="Q1", query_text="FastAPI overview", intent="Overview")],
        sources=[
            SourceDocument(
                id="S1",
                title="FastAPI Docs",
                url="https://fastapi.tiangolo.com",
                snippet="Modern framework for Python APIs.",
                is_mock=True,
            )
        ],
        key_findings=["FastAPI provides high performance and type hints [S1]."],
        supporting_evidence=[
            EvidenceClaim(
                claim_id="C1",
                claim_text="FastAPI provides high performance.",
                supporting_source_ids=["S1"],
                status="supported",
            )
        ],
        conflicting_evidence=[],
        unanswered_questions=[],
        sources_sufficient=True,
        limitations=["Testing limitation."],
    )


# ==============================================================================
# 1. Database Storage & Persistence Unit Tests
# ==============================================================================

def test_db_initialization(tmp_path: Path):
    db_file = tmp_path / "init_check.db"
    db = ResearchDatabase(db_path=db_file)
    assert db_file.exists()
    # Confirm tables are ready
    records, total = db.list_records()
    assert total == 0
    assert records == []


def test_save_and_get_record(temp_db: ResearchDatabase, sample_report: ResearchReport):
    rec_id = temp_db.save_report(sample_report)
    assert rec_id is not None

    record = temp_db.get_record(rec_id)
    assert record is not None
    assert record["id"] == rec_id
    assert record["question"] == "What is FastAPI?"
    assert record["status"] == "completed"
    assert record["report"].research_question == sample_report.research_question
    assert len(record["report"].key_findings) == 1
    assert record["report"].key_findings[0] == sample_report.key_findings[0]


def test_get_unknown_record(temp_db: ResearchDatabase):
    record = temp_db.get_record("non_existent_id_12345")
    assert record is None


def test_list_records_pagination(temp_db: ResearchDatabase, sample_report: ResearchReport):
    for i in range(5):
        rep = sample_report.model_copy()
        rep.research_question = f"Question {i}"
        temp_db.save_report(rep)

    records, total = temp_db.list_records(limit=2, offset=0)
    assert total == 5
    assert len(records) == 2

    records_page_2, _ = temp_db.list_records(limit=2, offset=2)
    assert len(records_page_2) == 2
    assert records[0]["id"] != records_page_2[0]["id"]


def test_search_records(temp_db: ResearchDatabase, sample_report: ResearchReport):
    sample_report.research_question = "Explain Python GIL concurrency"
    temp_db.save_report(sample_report)

    results = temp_db.search_records("concurrency")
    assert len(results) == 1
    assert "concurrency" in results[0]["question"].lower()

    # Search non-matching
    no_results = temp_db.search_records("astrophysics")
    assert len(no_results) == 0


def test_delete_record(temp_db: ResearchDatabase, sample_report: ResearchReport):
    rec_id = temp_db.save_report(sample_report)
    assert temp_db.get_record(rec_id) is not None

    deleted = temp_db.delete_record(rec_id)
    assert deleted is True
    assert temp_db.get_record(rec_id) is None

    # Deleting again returns False
    assert temp_db.delete_record(rec_id) is False


# ==============================================================================
# 2. Report Comparison Service Tests
# ==============================================================================

def test_compare_research_reports():
    rep_a = ResearchReport(
        research_question="Topic A",
        executive_summary="Summary A",
        sources=[SourceDocument(id="S1", title="Source 1", url="https://example.com/1", snippet="Snippet 1")],
        key_findings=["Shared Finding [S1]", "Finding Only In A [S1]"],
        supporting_evidence=[],
        conflicting_evidence=[],
        unanswered_questions=[],
        sources_sufficient=True,
        limitations=["Limitation A"],
    )

    rep_b = ResearchReport(
        research_question="Topic B",
        executive_summary="Summary B",
        sources=[SourceDocument(id="S2", title="Source 2", url="https://example.com/2", snippet="Snippet 2")],
        key_findings=["Shared Finding [S2]", "Finding Only In B [S2]"],
        supporting_evidence=[],
        conflicting_evidence=[
            EvidenceClaim(
                claim_id="C1",
                claim_text="Disputed metric found in Report B",
                supporting_source_ids=["S2"],
                status="conflicting",
            )
        ],
        unanswered_questions=[],
        sources_sufficient=True,
        limitations=["Limitation B"],
    )

    comparison = compare_research_reports(rep_a, rep_b, id_a="REC-1", id_b="REC-2")

    assert comparison["id_a"] == "REC-1"
    assert comparison["id_b"] == "REC-2"
    assert len(comparison["shared_findings"]) == 1
    assert "Shared Finding" in comparison["shared_findings"][0]
    assert len(comparison["findings_only_in_a"]) == 1
    assert "Finding Only In A" in comparison["findings_only_in_a"][0]
    assert len(comparison["findings_only_in_b"]) == 1
    assert "Finding Only In B" in comparison["findings_only_in_b"][0]
    assert len(comparison["conflicting_claims"]) == 1
    assert len(comparison["sources_a"]) == 1
    assert len(comparison["sources_b"]) == 1


# ==============================================================================
# 3. FastAPI Endpoint Integration Tests
# ==============================================================================

def test_api_execute_and_save_research():
    response = client.post(
        "/api/research",
        json={"question": "What is Python and why is it popular?", "max_subqueries": 2, "max_sources": 3},
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["question"] == "What is Python and why is it popular?"
    assert data["status"] in ["completed", "insufficient"]
    assert "report" in data

    research_id = data["id"]

    # Verify retrieval via GET /api/research/{id}
    get_res = client.get(f"/api/research/{research_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == research_id


def test_api_list_saved_research():
    response = client.get("/api/research?limit=10&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert "records" in data
    assert "total" in data
    assert isinstance(data["records"], list)


def test_api_search_saved_research():
    # Insert record first
    client.post(
        "/api/research",
        json={"question": "Explain FastAPI high throughput benchmarks", "max_subqueries": 2},
    )
    search_res = client.get("/api/research/search?q=throughput")
    assert search_res.status_code == 200
    results = search_res.json()
    assert len(results) >= 1
    assert any("throughput" in r["question"].lower() for r in results)


def test_api_compare_saved_research():
    res1 = client.post("/api/research", json={"question": "FastAPI advantages", "max_subqueries": 2})
    res2 = client.post("/api/research", json={"question": "Python language background", "max_subqueries": 2})

    id1 = res1.json()["id"]
    id2 = res2.json()["id"]

    compare_res = client.get(f"/api/research/compare?id_a={id1}&id_b={id2}")
    assert compare_res.status_code == 200
    comp_data = compare_res.json()
    assert comp_data["id_a"] == id1
    assert comp_data["id_b"] == id2
    assert "comparison_summary" in comp_data


def test_api_get_unknown_research_404():
    response = client.get("/api/research/unknown-uuid-9999")
    assert response.status_code == 404


def test_api_delete_research():
    # Create record
    res = client.post("/api/research", json={"question": "Temporary research to delete", "max_subqueries": 2})
    rec_id = res.json()["id"]

    # Delete
    del_res = client.delete(f"/api/research/{rec_id}")
    assert del_res.status_code == 200
    assert del_res.json()["id"] == rec_id

    # Verify 404 after deletion
    assert client.get(f"/api/research/{rec_id}").status_code == 404
