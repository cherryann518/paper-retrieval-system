"""
Persist live search results to SQLite for the History tab.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from src.config import HISTORY_RETENTION_DAYS, OUTPUTS_DIR

HISTORY_DB_PATH = OUTPUTS_DIR / "history.db"
DEFAULT_LIST_LIMIT = 50

_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    paper_count INTEGER NOT NULL,
    duration_ms REAL,
    result_json TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(HISTORY_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _purge_old_entries(conn: sqlite3.Connection) -> int:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=HISTORY_RETENTION_DAYS)
    ).isoformat()
    cursor = conn.execute(
        "DELETE FROM search_sessions WHERE created_at < ?",
        (cutoff,),
    )
    return cursor.rowcount


def save_search(result: dict, duration_ms: float | None = None) -> int:
    papers = result.get("papers_display") or result.get("papers") or []
    payload = {
        "query": result["query"],
        "search_query": result.get("search_query", result["query"]),
        "papers": papers,
        "status": result.get("status", "unknown"),
        "metrics": result.get("metrics") or {},
        "fetch_errors": result.get("fetch_errors") or [],
        "run_id": result.get("run_id"),
    }
    created_at = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        deleted = _purge_old_entries(conn)
        if deleted:
            print(
                f"[history] purged {deleted} entries older than {HISTORY_RETENTION_DAYS} days",
                flush=True,
            )
        cursor = conn.execute(
            """
            INSERT INTO search_sessions (
                query, created_at, status, paper_count, duration_ms, result_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload["query"],
                created_at,
                payload["status"],
                len(papers),
                duration_ms,
                json.dumps(payload),
            ),
        )
        return int(cursor.lastrowid)


def list_history(limit: int = DEFAULT_LIST_LIMIT) -> list[dict]:
    with _connect() as conn:
        _purge_old_entries(conn)
        rows = conn.execute(
            """
            SELECT id, query, created_at, status, paper_count
            FROM search_sessions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_search(session_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, created_at, result_json FROM search_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    result = json.loads(row["result_json"])
    result["id"] = row["id"]
    result["created_at"] = row["created_at"]
    return result
