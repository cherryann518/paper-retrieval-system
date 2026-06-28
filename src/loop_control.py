"""
Cross-run query state (G1/G2/G3) — deterministic loop feedback foundation.
"""

from __future__ import annotations

from typing import Any

from src.config import DEAD_QUERY_THRESHOLD
from src.store import _connect, _utc_now_iso, init_db


def record_query_outcome(
    query: str,
    *,
    accepted_count: int,
    rejected_count: int,
    error_count: int,
    db_path=None,
) -> None:
    """Persist per-query run outcome for the next run's loop-control hooks."""
    init_db(db_path)
    now = _utc_now_iso()
    q = query.strip()

    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT consecutive_zero_accept FROM query_state WHERE query = ?",
            (q,),
        ).fetchone()

        if accepted_count == 0:
            consecutive = (row["consecutive_zero_accept"] + 1) if row else 1
        else:
            consecutive = 0

        conn.execute(
            """
            INSERT INTO query_state (
                query, last_run_at, accepted_count, rejected_count,
                error_count, consecutive_zero_accept
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(query) DO UPDATE SET
                last_run_at = excluded.last_run_at,
                accepted_count = excluded.accepted_count,
                rejected_count = excluded.rejected_count,
                error_count = excluded.error_count,
                consecutive_zero_accept = excluded.consecutive_zero_accept
            """,
            (q, now, accepted_count, rejected_count, error_count, consecutive),
        )
        conn.commit()


def get_query_state(query: str, *, db_path=None) -> dict[str, Any] | None:
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM query_state WHERE query = ?",
            (query.strip(),),
        ).fetchone()
    return dict(row) if row else None


def filter_dead_queries(
    queries: list[str],
    *,
    threshold: int = DEAD_QUERY_THRESHOLD,
    survey_mode: bool = False,
    db_path=None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """
    G3 — Skip queries with consecutive_zero_accept >= threshold in survey mode.

    Never returns an empty list: if every query would be skipped, the first
    (primary user) query is kept.
    """
    if not survey_mode or threshold <= 0 or not queries:
        return queries, []

    active: list[str] = []
    skipped: list[dict[str, Any]] = []

    for q in queries:
        state = get_query_state(q, db_path=db_path)
        consecutive = state["consecutive_zero_accept"] if state else 0
        if consecutive >= threshold:
            skipped.append(
                {
                    "query": q,
                    "consecutive_zero_accept": consecutive,
                    "reason": "dead_query_threshold",
                }
            )
        else:
            active.append(q)

    if not active:
        primary = queries[0]
        active = [primary]
        skipped = [s for s in skipped if s["query"] != primary]

    return active, skipped
