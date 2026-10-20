# DevPilot AI 🚀

DevPilot AI is an AI software engineering agent designed to investigate Python bugs, search codebases, propose precise code fixes, and verify them using automated tests.

---

## 📁 Project Structure

```text
DevPilot AI/
├── app/
│   ├── __init__.py        # App package marker
│   ├── agent/
│   │   ├── __init__.py    # Agent exports
│   │   ├── orchestrator.py# Bounded investigation loop & deterministic decision policy
│   │   └── state.py       # Typed Pydantic models (Steps, Evidence, Report)
│   └── tools/
│       ├── __init__.py    # Tools exports (list_project_files, search_code, resolve_safe_path)
│       ├── code_search.py # Stream-based text search within Python source files
│       └── project_inspector.py # Directory tree walker with ignored dirs and limits
├── tests/
│   ├── __init__.py        # Tests package marker
│   ├── test_agent.py      # Day 3 agent unit & integration tests (10 tests)
│   ├── test_main.py       # Day 1 endpoint tests (GET / and GET /health)
│   └── test_tools.py      # Day 2 tool unit & security tests (21 tests)
├── .gitignore             # Ignores virtual environments, caches, and secrets
├── main.py                # FastAPI app entry point with investigation & tools API endpoints
├── README.md              # Project documentation and quickstart guide
└── requirements.txt       # Production & testing dependencies
```

---

## 🛠️ Windows Setup Guide

Follow these steps using **Command Prompt (cmd)** or **PowerShell**.

### 1. Check Python Installation
Make sure Python 3.10+ is installed:
```powershell
python --version
```

### 2. Create a Virtual Environment
```powershell
python -m venv venv
```

### 3. Activate the Virtual Environment
- **PowerShell**:
  ```powershell
  .\venv\Scripts\Activate.ps1
  ```
- **Command Prompt (CMD)**:
  ```cmd
  venv\Scripts\activate.bat
  ```

### 4. Install Dependencies
```powershell
pip install -r requirements.txt
```

---

## 🏃 Running the Application

Start the local development server on port **3000**:
```powershell
uvicorn main:app --reload --port 3000
```

The server is available at:
- **Base URL**: [http://127.0.0.1:3000](http://127.0.0.1:3000)
- **Health Check**: [http://127.0.0.1:3000/health](http://127.0.0.1:3000/health)
- **Interactive Swagger Docs**: [http://127.0.0.1:3000/docs](http://127.0.0.1:3000/docs)
- **Alternative Redoc**: [http://127.0.0.1:3000/redoc](http://127.0.0.1:3000/redoc)

---

## 🤖 Investigation Agent API

### Endpoint: `POST /api/agent/investigate`

Coordinates a bounded investigation workflow within the codebase:
1. Maps project layout.
2. Extracts high-signal candidate terms (functions, identifiers, error names, quoted phrases).
3. Searches codebase files and collects matching lines with 1-indexed numbers.
4. Synthesizes a structured report while strictly distinguishing verifiable **evidence** from unconfirmed **hypotheses**.

#### Request Example:
```json
{
  "bug_description": "read_health endpoint returns unexpected status",
  "max_steps": 5
}
```

#### Response Example:
```json
{
  "bug_description": "read_health endpoint returns unexpected status",
  "status": "completed",
  "total_steps": 2,
  "steps_taken": [
    {
      "step_number": 1,
      "thought": "Inspect the project directory to map the codebase layout and locate Python files.",
      "action": "inspect_project",
      "parameters": {},
      "observation": { "success": true, "tool_name": "inspect_project", ... }
    },
    {
      "step_number": 2,
      "thought": "Search the Python source files for candidate symbol or keyword 'read_health'.",
      "action": "search_code",
      "parameters": { "query": "read_health" },
      "observation": { "success": true, "tool_name": "search_code", ... }
    }
  ],
  "observed_evidence": [
    {
      "file": "main.py",
      "line_number": 67,
      "line_content": "def read_health():",
      "search_query": "read_health"
    }
  ],
  "suspected_root_cause": "Candidate symbols (read_health) were located in main.py. These code locations may relate to the reported issue, but root cause requires manual verification.",
  "summary": "Investigation completed across 2 step(s). Found 1 matching evidence line(s) across 1 file(s)."
}
```

---

## 🧪 Running Automated Tests

Run the complete test suite using `pytest`:
```powershell
python -m pytest -v
```
*(Or `.\venv\Scripts\python.exe -m pytest -v`)*

---

## 🛣️ Roadmap

- **Day 1**: Project foundation, FastAPI setup, and automated endpoint tests. *(Completed)*
- **Day 2**: Codebase inspection tools (directory scanner, file reader, safe code search). *(Completed)*
- **Day 3**: Investigation agent (bounded orchestrator, deterministic policy, evidence vs hypothesis separation). *(Completed)*
- **Day 4**: Fix proposal engine & patch generation.
- **Day 5**: Automated fix verification & regression testing.
