import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.research.state import ResearchReport


DEFAULT_DB_PATH = Path("data/research_memory.db")


class ResearchDatabase:
    """
    SQLite-backed persistent research memory.
    Uses parameterized SQL queries, strict transaction management,
    and safe JSON serialization. Does not store API keys or secrets.
    """

    def __init__(self, db_path: Optional[str | Path] = None):
        if db_path is None:
            env_path = os.getenv("DATABASE_PATH")
            self.db_path = Path(env_path) if env_path else DEFAULT_DB_PATH
        else:
            self.db_path = Path(db_path)

        # Ensure database directory exists
        if self.db_path != Path(":memory:") and self.db_path.parent != Path("."):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Opens a connection with row factory configured."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Creates tables and indexes automatically."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS research_records (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    sources_summary_json TEXT NOT NULL,
                    limitations_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_question ON research_records (question)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_created ON research_records (created_at DESC)"
            )
            conn.commit()

    def save_report(
        self,
        report: ResearchReport,
        research_id: Optional[str] = None,
    ) -> str:
        """
        Saves a structured ResearchReport to SQLite.
        Returns the unique research_id.
        """
        rec_id = research_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Serialize report to dict and JSON safely
        report_dict = report.model_dump()
        report_json = json.dumps(report_dict)

        # Extract source metadata summary
        sources_summary = [
            {"id": s.id, "title": s.title, "url": s.url, "is_mock": s.is_mock}
            for s in report.sources
        ]
        sources_json = json.dumps(sources_summary)
        limitations_json = json.dumps(report.limitations)

        status = "completed" if report.sources_sufficient else "insufficient"

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO research_records (
                    id, question, status, report_json, sources_summary_json, limitations_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    question=excluded.question,
                    status=excluded.status,
                    report_json=excluded.report_json,
                    sources_summary_json=excluded.sources_summary_json,
                    limitations_json=excluded.limitations_json,
                    updated_at=excluded.updated_at
                """,
                (
                    rec_id,
                    report.research_question,
                    status,
                    report_json,
                    sources_json,
                    limitations_json,
                    now,
                    now,
                ),
            )
            conn.commit()

        return rec_id

    def get_record(self, research_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a saved research record and deserializes the full ResearchReport.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, question, status, report_json, created_at, updated_at
                FROM research_records
                WHERE id = ?
                """,
                (research_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            report_data = json.loads(row["report_json"])
            return {
                "id": row["id"],
                "question": row["question"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "report": ResearchReport.model_validate(report_data),
            }

    def list_records(
        self, limit: int = 20, offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Lists saved research summaries with pagination.
        Returns: (list_of_summaries, total_count)
        """
        with self._get_connection() as conn:
            # Count total
            total_cursor = conn.execute("SELECT COUNT(*) AS total FROM research_records")
            total = total_cursor.fetchone()["total"]

            # Fetch page
            cursor = conn.execute(
                """
                SELECT id, question, status, sources_summary_json, report_json, created_at
                FROM research_records
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
            records: List[Dict[str, Any]] = []
            for row in cursor.fetchall():
                sources = json.loads(row["sources_summary_json"])
                report_dict = json.loads(row["report_json"])
                records.append(
                    {
                        "id": row["id"],
                        "question": row["question"],
                        "status": row["status"],
                        "created_at": row["created_at"],
                        "sources_count": len(sources),
                        "findings_count": len(report_dict.get("key_findings", [])),
                    }
                )

            return records, total

    def search_records(
        self, query: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Searches previous research records by question or content using parameterized LIKE.
        """
        clean_query = f"%{query.strip()}%"
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, question, status, sources_summary_json, report_json, created_at
                FROM research_records
                WHERE question LIKE ? OR report_json LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (clean_query, clean_query, limit),
            )
            results: List[Dict[str, Any]] = []
            for row in cursor.fetchall():
                sources = json.loads(row["sources_summary_json"])
                report_dict = json.loads(row["report_json"])
                results.append(
                    {
                        "id": row["id"],
                        "question": row["question"],
                        "status": row["status"],
                        "created_at": row["created_at"],
                        "sources_count": len(sources),
                        "findings_count": len(report_dict.get("key_findings", [])),
                    }
                )
            return results

    def delete_record(self, research_id: str) -> bool:
        """
        Deletes a research record by ID.
        Returns True if a row was deleted, False if record did not exist.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM research_records WHERE id = ?",
                (research_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
