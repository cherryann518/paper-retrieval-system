"""
Fuzzy title duplicate detection (E4) — flag only, never auto-merge.
"""

from __future__ import annotations

import re
import sqlite3

from src.schema import PaperRecord

FUZZY_MATCH_TYPE = "fuzzy_title_year"
MIN_TITLE_LEN = 10
YEAR_TOLERANCE = 1


def normalize_fuzzy_title(title: str | None) -> str:
    """Lowercase, strip punctuation, drop subtitle after colon, collapse whitespace."""
    if not title:
        return ""
    text = title.lower().strip()
    if ":" in text and len(text.split(":", 1)[0]) >= MIN_TITLE_LEN:
        text = text.split(":", 1)[0]
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def years_compatible(year_a: int | None, year_b: int | None) -> bool:
    if year_a is None or year_b is None:
        return True
    return abs(year_a - year_b) <= YEAR_TOLERANCE


def find_fuzzy_title_matches(
    conn: sqlite3.Connection,
    record: PaperRecord,
) -> list[sqlite3.Row]:
    norm = normalize_fuzzy_title(record.title)
    if len(norm) < MIN_TITLE_LEN:
        return []
    rows = conn.execute(
        """
        SELECT paper_id, title, year FROM papers
        WHERE title_normalized = ? AND paper_id != ?
        """,
        (norm, record.paper_id),
    ).fetchall()
    return [row for row in rows if years_compatible(record.year, row["year"])]


def _ordered_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def flag_fuzzy_duplicates(
    conn: sqlite3.Connection,
    record: PaperRecord,
    *,
    now: str,
) -> int:
    """Insert possible_duplicates rows for fuzzy title+year matches. Returns new flags."""
    flagged = 0
    for row in find_fuzzy_title_matches(conn, record):
        pid_a, pid_b = _ordered_pair(record.paper_id, row["paper_id"])
        cursor = conn.execute(
            """
            INSERT INTO possible_duplicates (
                paper_id_a, paper_id_b, match_type, score, seen_at
            ) VALUES (?, ?, ?, 1.0, ?)
            ON CONFLICT(paper_id_a, paper_id_b, match_type) DO NOTHING
            """,
            (pid_a, pid_b, FUZZY_MATCH_TYPE, now),
        )
        if cursor.rowcount:
            flagged += 1
    return flagged
