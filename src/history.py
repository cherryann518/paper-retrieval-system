"""
Persist live search results to SQLite for the History tab.

Not used in offline mode. No caching — every live search runs the agent fresh.
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
    refinement_rounds INTEGER NOT NULL,
    search_queries_used TEXT NOT NULL,
    acceptance_reason TEXT NOT NULL,
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
    """Delete sessions older than HISTORY_RETENTION_DAYS. Returns rows deleted."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=HISTORY_RETENTION_DAYS)
    ).isoformat()
    cursor = conn.execute(
        "DELETE FROM search_sessions WHERE created_at < ?",
        (cutoff,),
    )
    return cursor.rowcount


def save_search(result: dict, duration_ms: float | None = None) -> int:
    """Store one live search result. Returns the new session id."""
    papers = result.get("papers") or []
    payload = {
        "query": result["query"],
        "papers": papers,
        "status": result.get("status", "unknown"),
        "refinement_rounds": result.get("refinement_rounds", 0),
        "search_queries_used": result.get("search_queries_used") or [result["query"]],
        "acceptance_reason": result.get("acceptance_reason", ""),
    }
    created_at = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        deleted = _purge_old_entries(conn)
        if deleted:
            print(f"[history] purged {deleted} entr{'y' if deleted == 1 else 'ies'} older than {HISTORY_RETENTION_DAYS} days", flush=True)

        cursor = conn.execute(
            """
            INSERT INTO search_sessions (
                query, created_at, status, refinement_rounds,
                search_queries_used, acceptance_reason,
                paper_count, duration_ms, result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["query"],
                created_at,
                payload["status"],
                payload["refinement_rounds"],
                json.dumps(payload["search_queries_used"]),
                payload["acceptance_reason"],
                len(papers),
                duration_ms,
                json.dumps(payload),
            ),
        )
        return int(cursor.lastrowid)


def list_history(limit: int = DEFAULT_LIST_LIMIT) -> list[dict]:
    """Return recent sessions (newest first), without full paper payloads."""
    with _connect() as conn:
        deleted = _purge_old_entries(conn)
        if deleted:
            print(f"[history] purged {deleted} entr{'y' if deleted == 1 else 'ies'} older than {HISTORY_RETENTION_DAYS} days", flush=True)

        rows = conn.execute(
            """
            SELECT id, query, created_at, status, refinement_rounds, paper_count
            FROM search_sessions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_search(session_id: int) -> dict | None:
    """Return a saved search result by id, or None if missing."""
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
