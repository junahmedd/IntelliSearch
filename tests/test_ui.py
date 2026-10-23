from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_dashboard_endpoint():
    """
    Test GET /dashboard serves HTML dashboard page with status 200.
    """
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "IntelliResearch" in response.text
    assert "id=\"questionInput\"" in response.text
    assert "id=\"startResearchBtn\"" in response.text
    assert "id=\"historyList\"" in response.text


def test_ui_alias_endpoint():
    """
    Test GET /ui serves HTML dashboard page as alias with status 200.
    """
    response = client.get("/ui")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "IntelliResearch" in response.text


def test_static_css_served():
    """
    Test GET /static/style.css serves the dark theme stylesheet.
    """
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers.get("content-type", "")
    assert "--bg-primary" in response.text


def test_static_js_served():
    """
    Test GET /static/app.js serves the frontend client script with Day 8 enhancements.
    """
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert "javascript" in response.headers.get("content-type", "")
    assert "executeResearch" in response.text
    assert "formatErrorMessage" in response.text
    assert "isSubmitting" in response.text


def test_root_endpoint_compatibility():
    """
    Ensure root endpoint / remains preserved for Day 1 compatibility.
    """
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Welcome to DevPilot AI!"
    assert data["status"] == "running"
    assert data["version"] == "0.1.0"


def test_research_submission_and_report_schema_contract():
    """
    Phase 2: Verify submit endpoint returns exact ResearchRecordResponse matching UI expectations.
    """
    payload = {
        "question": "What is Python asyncio event loop?",
        "max_subqueries": 2,
        "max_sources": 4,
        "use_llm": False,
    }
    response = client.post("/api/research", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["question"] == payload["question"]
    assert data["status"] in ("completed", "insufficient")
    assert "created_at" in data

    report = data["report"]
    assert "research_question" in report
    assert "executive_summary" in report
    assert "key_findings" in report
    assert isinstance(report["key_findings"], list)
    assert "sources" in report
    assert isinstance(report["sources"], list)
    for src in report["sources"]:
        assert "id" in src
        assert "url" in src
        assert "title" in src


def test_research_history_search_and_pagination():
    """
    Phase 3: Verify GET /api/research pagination and search filtering.
    """
    # Create distinct record to search
    unique_term = "UniqueSearchTermDay8"
    client.post("/api/research", json={"question": f"Research on {unique_term} details"})

    # Search for it
    search_resp = client.get(f"/api/research/search?q={unique_term}")
    assert search_resp.status_code == 200
    results = search_resp.json()
    assert len(results) >= 1
    assert any(unique_term in r["question"] for r in results)

    # Paginated listing
    list_resp = client.get("/api/research?limit=5&offset=0")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert "records" in list_data
    assert "total" in list_data
    assert len(list_data["records"]) <= 5


def test_research_compare_contract():
    """
    Phase 4: Verify comparison endpoint provides all fields expected by comparison modal.
    """
    r1 = client.post("/api/research", json={"question": "Compare Topic Alpha 123"}).json()
    r2 = client.post("/api/research", json={"question": "Compare Topic Beta 456"}).json()

    comp_resp = client.get(f"/api/research/compare?id_a={r1['id']}&id_b={r2['id']}")
    assert comp_resp.status_code == 200
    comp_data = comp_resp.json()
    assert "shared_findings" in comp_data
    assert "findings_only_in_a" in comp_data
    assert "findings_only_in_b" in comp_data
    assert "conflicting_claims" in comp_data
    assert "sources_a" in comp_data
    assert "sources_b" in comp_data
    assert "limitations_a" in comp_data
    assert "limitations_b" in comp_data
    assert "comparison_summary" in comp_data


def test_research_delete_updates_history():
    """
    Phase 3: Verify delete removes record and subsequent GET returns 404.
    """
    created = client.post("/api/research", json={"question": "Record to be deleted immediately"}).json()
    rec_id = created["id"]

    # Verify exists
    assert client.get(f"/api/research/{rec_id}").status_code == 200

    # Delete
    del_resp = client.delete(f"/api/research/{rec_id}")
    assert del_resp.status_code == 200

    # Verify deleted
    assert client.get(f"/api/research/{rec_id}").status_code == 404


def test_ui_validation_error_responses():
    """
    Phase 2 & 5: Test validation errors return 422 with structured details for UI error handling.
    """
    # Question too short (< 4 characters)
    resp = client.post("/api/research", json={"question": "abc"})
    assert resp.status_code == 422
    data = resp.json()
    assert "detail" in data

    # Exceeding max subqueries (> 5)
    resp = client.post("/api/research", json={"question": "Valid Question Here", "max_subqueries": 10})
    assert resp.status_code == 422
