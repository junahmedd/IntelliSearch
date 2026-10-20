import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.tools.project_inspector import (
    DEFAULT_IGNORED_DIRS,
    list_project_files,
    resolve_safe_path,
)
from app.tools.code_search import search_code
from main import app

client = TestClient(app)


@pytest.fixture
def sample_project(tmp_path: Path):
    """
    Creates a temporary project tree with:
    - Root and nested python files
    - Non-python files
    - Ignored directories (.git, .venv, venv, __pycache__, .pytest_cache)
    - A large file
    """
    proj = tmp_path / "my_project"
    proj.mkdir()

    # Normal python files
    (proj / "app.py").write_text("def run():\n    print('DevPilot AI running')\n", encoding="utf-8")
    
    src = proj / "src"
    src.mkdir()
    (src / "calculator.py").write_text(
        "def add(a, b):\n    # TODO: optimize addition\n    return a + b\n",
        encoding="utf-8",
    )

    # Non-python file
    (proj / "notes.txt").write_text("TODO: update documentation\n", encoding="utf-8")

    # Ignored directories
    for ignored in DEFAULT_IGNORED_DIRS:
        ignored_dir = proj / ignored
        ignored_dir.mkdir()
        (ignored_dir / "ignored_script.py").write_text(
            "# TODO: should never be discovered or searched\n",
            encoding="utf-8",
        )

    # Large file (> 1 KB for testing small threshold)
    large_file = proj / "large.py"
    large_file.write_text("x = 1\n" * 500, encoding="utf-8")

    return proj


# ==========================================
# 1. Path Safety & Inspector Tests
# ==========================================

def test_resolve_safe_path_valid(sample_project: Path):
    resolved = resolve_safe_path(sample_project / "src", base_dir=sample_project)
    assert resolved == (sample_project / "src").resolve()


def test_resolve_safe_path_traversal(sample_project: Path, tmp_path: Path):
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    with pytest.raises(ValueError, match="Path traversal detected"):
        resolve_safe_path(outside_dir, base_dir=sample_project)


def test_resolve_safe_path_nonexistent(sample_project: Path):
    with pytest.raises(FileNotFoundError):
        resolve_safe_path(sample_project / "non_existent_folder")


def test_list_project_files_basic(sample_project: Path):
    result = list_project_files(sample_project)
    assert result["truncated"] is False
    assert result["total_files"] >= 3

    rel_paths = [f["relative_path"] for f in result["files"]]
    assert "app.py" in rel_paths
    assert "src/calculator.py" in rel_paths
    assert "notes.txt" in rel_paths


def test_list_project_files_skips_ignored_directories(sample_project: Path):
    result = list_project_files(sample_project)
    rel_paths = [f["relative_path"] for f in result["files"]]

    for ignored in DEFAULT_IGNORED_DIRS:
        for path in rel_paths:
            assert not path.startswith(f"{ignored}/"), f"Found ignored directory file: {path}"


def test_list_project_files_max_files_limit(sample_project: Path):
    result = list_project_files(sample_project, max_files=2)
    assert len(result["files"]) == 2
    assert result["total_files"] == 2
    assert result["truncated"] is True


def test_list_project_files_size_limit(sample_project: Path):
    # Set size limit smaller than the 500-line large.py
    result = list_project_files(sample_project, max_file_size_bytes=200)
    rel_paths = [f["relative_path"] for f in result["files"]]
    assert "large.py" not in rel_paths
    assert "app.py" in rel_paths


# ==========================================
# 2. Code Search Tests
# ==========================================

def test_code_search_matches(sample_project: Path):
    result = search_code(sample_project, query="TODO")
    assert result["query"] == "TODO"
    assert result["total_matches"] == 1
    assert result["truncated"] is False

    match = result["matches"][0]
    assert match["file"] == "src/calculator.py"
    assert match["line_number"] == 2
    assert "TODO: optimize addition" in match["line_content"]


def test_code_search_missing_term(sample_project: Path):
    result = search_code(sample_project, query="non_existent_symbol_xyz")
    assert result["total_matches"] == 0
    assert result["matches"] == []
    assert result["truncated"] is False


def test_code_search_case_sensitivity(sample_project: Path):
    # Case insensitive finds 'devpilot'
    insensitive_result = search_code(sample_project, query="devpilot", case_sensitive=False)
    assert insensitive_result["total_matches"] == 1

    # Case sensitive does not find lowercase 'devpilot' (it's 'DevPilot')
    sensitive_result = search_code(sample_project, query="devpilot", case_sensitive=True)
    assert sensitive_result["total_matches"] == 0


def test_code_search_skips_ignored_directories(sample_project: Path):
    # 'should never be discovered' is inside all ignored directories
    result = search_code(sample_project, query="should never be discovered")
    assert result["total_matches"] == 0


def test_code_search_skips_non_python_files(sample_project: Path):
    # notes.txt has 'update documentation', but default searches only .py
    result = search_code(sample_project, query="update documentation")
    assert result["total_matches"] == 0


def test_code_search_max_results_limit(sample_project: Path):
    # 'x = 1' appears 500 times in large.py
    result = search_code(sample_project, query="x = 1", max_results=5)
    assert result["total_matches"] == 5
    assert len(result["matches"]) == 5
    assert result["truncated"] is True


def test_code_search_file_size_limit(sample_project: Path):
    # Skip files larger than 100 bytes
    result = search_code(sample_project, query="x = 1", max_file_size_bytes=100)
    assert result["total_matches"] == 0


def test_code_search_empty_query(sample_project: Path):
    with pytest.raises(ValueError, match="Search query cannot be empty"):
        search_code(sample_project, query="")


# ==========================================
# 3. API Integration & Safety Tests
# ==========================================

def test_api_inspect_endpoint():
    response = client.post("/api/tools/inspect", json={"subpath": ".", "max_files": 100})
    assert response.status_code == 200
    data = response.json()
    assert "files" in data
    assert "total_files" in data
    # Ensure main.py is reported
    files = [f["relative_path"] for f in data["files"]]
    assert "main.py" in files


def test_api_inspect_endpoint_traversal_blocked():
    # Attempt directory traversal out of the workspace
    response = client.post("/api/tools/inspect", json={"subpath": "../../"})
    assert response.status_code == 400
    assert "Path traversal detected" in response.json()["detail"]


def test_api_search_endpoint():
    response = client.post(
        "/api/tools/search",
        json={"query": "read_health", "subpath": ".", "max_results": 10},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "read_health"
    assert data["total_matches"] >= 1
    assert any(m["file"] == "main.py" for m in data["matches"])


def test_api_search_endpoint_traversal_blocked():
    response = client.post(
        "/api/tools/search",
        json={"query": "test", "subpath": "../../../"},
    )
    assert response.status_code == 400
    assert "Path traversal detected" in response.json()["detail"]


def test_api_inspect_get_endpoint():
    response = client.get("/api/tools/inspect")
    assert response.status_code == 200
    data = response.json()
    assert "files" in data
    assert any(f["relative_path"] == "main.py" for f in data["files"])


def test_api_search_get_endpoint():
    response = client.get("/api/tools/search?query=read_health")
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "read_health"
    assert data["total_matches"] >= 1

