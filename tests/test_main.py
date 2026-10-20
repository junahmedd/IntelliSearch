from fastapi.testclient import TestClient
from main import app

# Initialize test client with the FastAPI app instance
client = TestClient(app)


def test_read_root():
    """
    Test GET / endpoint:
    - Status code should be 200 OK.
    - JSON payload should include welcome message, running status, and version.
    """
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Welcome to DevPilot AI!"
    assert data["status"] == "running"
    assert data["version"] == "0.1.0"


def test_read_health():
    """
    Test GET /health endpoint:
    - Status code should be 200 OK.
    - JSON payload should return {"status": "ok"}.
    """
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
