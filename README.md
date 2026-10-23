# DevPilot AI / IntelliResearch 🚀

DevPilot AI (IntelliResearch) is an evidence-based AI research and software engineering agent designed to investigate codebases, gather multi-source evidence, evaluate conflicting claims, synthesize grounded reports, and persist findings to a persistent SQLite memory library with report comparison.

---

## 📁 Project Structure

```text
DevPilot AI / IntelliResearch
├── app/
│   ├── __init__.py            # App package marker
│   ├── agent/                 # Day 3: Codebase Investigation Agent
│   │   ├── __init__.py        # Agent exports
│   │   ├── orchestrator.py    # Bounded codebase loop & deterministic decision policy
│   │   └── state.py           # Typed Pydantic models (Steps, Evidence, Report)
│   ├── research/              # Day 4, 5 & 6: Research Engine & Persistent Memory
│   │   ├── __init__.py        # Research exports
│   │   ├── comparison.py      # Day 6: Deterministic report comparison service
│   │   ├── database.py        # Day 6: SQLite persistent storage & parameterized queries
│   │   ├── evaluator.py       # Source deduplication, conflict detection & sanitization
│   │   ├── grounding.py       # Day 5: Strict hallucination defense & source verification
│   │   ├── llm.py             # Day 5: Provider-agnostic LLM client (Groq, Ollama, OpenAI)
│   │   ├── orchestrator.py    # Research workflow & deterministic fallback
│   │   ├── planner.py         # Subquery planning and query decomposition
│   │   ├── providers.py       # SearchProvider interface & DeterministicMockSearchProvider
│   │   └── state.py           # Typed models (SubQuery, SourceDocument, ResearchReport, etc.)
│   └── tools/                 # Day 2: Codebase Inspection Tools
│       ├── __init__.py        # Tools exports (list_project_files, search_code, resolve_safe_path)
│       ├── code_search.py     # Stream-based text search within Python source files
│       └── project_inspector.py # Directory tree walker with ignored dirs and limits
├── static/                 # Day 7: Web UI static assets
│   ├── app.js             # Vanilla ES6 client: research, history, compare modal
│   ├── index.html         # Responsive research dashboard UI
│   └── style.css          # Dark-theme design, status pills, and responsive layout
├── tests/
│   ├── __init__.py            # Tests package marker
│   ├── test_agent.py          # Day 3 agent tests (10 tests)
│   ├── test_database_and_history.py # Day 6 database & comparison tests (13 tests)
│   ├── test_evidence_synthesis.py   # Day 11 evidence synthesis & conflict distinction (7 tests)
│   ├── test_evidence_validation.py  # Day 10 URL validation, SSRF guard & traceability (10 tests)
│   ├── test_llm_grounding.py  # Day 5 LLM & grounding tests (12 tests)
│   ├── test_main.py           # Day 1 endpoint tests (2 tests)
│   ├── test_real_search.py    # Day 9 real-source search provider tests (10 tests)
│   ├── test_research.py       # Day 4 research agent tests (15 tests)
│   ├── test_tools.py          # Day 2 tool unit & security tests (21 tests)
│   └── test_ui.py             # Day 7 & 8 Web UI integration tests (10 tests)
├── .env.example               # Safe environment variable configuration template
├── .gitignore                 # Excludes venvs, caches, secrets (.env), and databases (*.db)
├── main.py                    # FastAPI app entry point with research, memory, and tool APIs
├── README.md                  # Project documentation and quickstart guide
└── requirements.txt           # Production & testing dependencies
```

---

## 🗄️ Database Schema & Storage Behavior (Day 6)

IntelliResearch uses Python's built-in `sqlite3` engine. Local databases are stored at `data/research_memory.db` (configurable via `DATABASE_PATH`). All `.db` and `.sqlite` files are excluded from Git via `.gitignore`.

### SQLite Schema (`research_records` Table):
```sql
CREATE TABLE IF NOT EXISTS research_records (
    id TEXT PRIMARY KEY,               -- UUID4 string
    question TEXT NOT NULL,            -- Original user research question
    status TEXT NOT NULL,              -- 'completed' or 'insufficient'
    report_json TEXT NOT NULL,         -- Full serialized ResearchReport (JSON)
    sources_summary_json TEXT NOT NULL,-- List of sources with URLs and IDs
    limitations_json TEXT NOT NULL,    -- Caveats, mock notices, or conflicts
    created_at TEXT NOT NULL,          -- ISO 8601 UTC timestamp
    updated_at TEXT NOT NULL           -- ISO 8601 UTC timestamp
);
CREATE INDEX IF NOT EXISTS idx_research_question ON research_records (question);
CREATE INDEX IF NOT EXISTS idx_research_created ON research_records (created_at DESC);
```

### Safety & Privacy Guarantees:
- **Parameterized SQL**: All database operations use `?` placeholders to eliminate SQL injection vulnerabilities.
- **Zero Secret Storage**: API keys, auth tokens, and system secrets are strictly excluded from the database.
- **Untrusted Input Treatment**: Web snippets and model outputs are validated and escaped prior to storage.

### How to Back Up or Reset the Database:
- **Backup**:
  ```powershell
  copy data\research_memory.db data\research_memory_backup.db
  ```
- **Reset**:
  ```powershell
  Remove-Item data\research_memory.db
  ```
  *(The database and schema are recreated automatically on the next request).*

---

## 📚 Persistent Research Memory APIs (Day 6)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/research` | Executes research, grounds findings, and permanently saves to SQLite memory. |
| `GET` | `/api/research` | Lists saved research records with pagination (`limit`, `offset`). |
| `GET` | `/api/research/search?q=...` | Searches previous questions and reports using SQL pattern matching. |
| `GET` | `/api/research/compare?id_a=...&id_b=...` | Deterministically compares two saved reports for shared, unique, and conflicting findings. |
| `GET` | `/api/research/{research_id}` | Retrieves a complete saved research record by ID. |
| `DELETE` | `/api/research/{research_id}` | Deletes a research record from memory. |

### 1. Execute & Save Research (`POST /api/research`)
```json
// Request:
{
  "question": "What is FastAPI and how does it perform?",
  "max_subqueries": 3,
  "max_sources": 6,
  "use_llm": false
}

// Response (HTTP 201 Created):
{
  "id": "e6a2139b-468a-4467-8eb1-71649e414c10",
  "question": "What is FastAPI and how does it perform?",
  "status": "completed",
  "created_at": "2026-10-22T02:07:00Z",
  "updated_at": "2026-10-22T02:07:00Z",
  "report": { ... }
}
```

### 2. Compare Two Reports (`GET /api/research/compare?id_a=...&id_b=...`)
```json
{
  "id_a": "rec-1",
  "id_b": "rec-2",
  "question_a": "FastAPI advantages",
  "question_b": "Python language background",
  "shared_findings": [
    "FastAPI is a modern web framework for Python. [S1]"
  ],
  "findings_only_in_a": [
    "Independent TechEmpower benchmarks show high throughput. [S2]"
  ],
  "findings_only_in_b": [
    "CPython uses a GIL for memory safety. [S1]"
  ],
  "conflicting_claims": [],
  "sources_a": [ ... ],
  "sources_b": [ ... ],
  "comparison_summary": "Comparison between 'rec-1' and 'rec-2': Found 1 shared finding(s), 1 finding(s) unique to report A, 1 finding(s) unique to report B, and 0 conflicting claim(s) requiring review."
}
```

---

## 🖥️ Interactive Web UI Dashboard (Day 7)

IntelliResearch features an interactive dark-theme Web UI served directly by FastAPI at `/dashboard` (or `/ui`):

- **Query Workspace**: Submit research questions with customizable subquery count (1-5), max sources (3-12), and optional LLM toggle.
- **Evidence-Grounded Reports**: Displays executive summary, findings with source citation tags (e.g., `[S1]`, `[S2]`), clickable verified source URLs, and conflict warnings.
- **Research Library Sidebar**: Real-time listing of saved research records with search filtering, status badges, and single-click deletion with safety confirmation.
- **Side-by-Side Comparison**: Select any 2 research records to launch an interactive comparison modal displaying shared findings, unique findings, and conflicting claims.
- **Zero-Dependency Architecture**: Built using native Vanilla HTML5/CSS3/JavaScript (ES6+) with strict HTML escaping to defend against prompt injection/XSS.

---

## 🏃 Running the Application

Start the local server:
```powershell
uvicorn main:app --reload --port 8080
```
- **Web UI Dashboard:** [http://127.0.0.1:8080/dashboard](http://127.0.0.1:8080/dashboard) (or `/ui`)
- **Swagger Documentation:** [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs)
- **Health Check:** [http://127.0.0.1:8080/health](http://127.0.0.1:8080/health)

---

## 🧪 Running Automated Tests

Run all 110 tests offline:
```powershell
python -m pytest -v
```

---

## 🛣️ Project Milestones

- **Day 1**: Foundation, FastAPI setup, and automated endpoint tests. *(Completed)*
- **Day 2**: Codebase inspection tools (directory scanner, file reader, safe code search). *(Completed)*
- **Day 3**: Codebase investigation agent (bounded orchestrator, deterministic policy). *(Completed)*
- **Day 4**: Evidence-based research agent (query planning, source collection, conflict detection, verifiable reports). *(Completed)*
- **Day 5**: LLM integration, prompt injection isolation, grounding validator, and offline resilience. *(Completed)*
- **Day 6**: Persistent research memory (SQLite library, history APIs, report comparison, search & deletion). *(Completed)*
- **Day 7**: Interactive Web UI Dashboard (modern dark-theme interface, research execution, library search, report comparison). *(Completed)*
- **Day 8**: Frontend & backend verification (resilience, timeout safeguards, validation schemas, history sync). *(Completed)*
- **Day 9**: Real-source web retrieval (DuckDuckGo live provider, Tavily adapter, search provider factory, offline fallback). *(Completed)*
- **Day 10**: Evidence validation & research quality (strict URL/SSRF protection, canonical deduplication, claim traceability, explainable quality signals). *(Completed)*
- **Day 11**: Evidence-grounded synthesis (fact vs. inference classification, strong dispute vs. scope contrast, cross-provider comparison normalization). *(Completed)*
