"""
SQLite main database for canonical paper storage.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import PAPERS_DB_PATH
from src.schema import PaperRecord


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or PAPERS_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS papers (
                paper_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                authors_json TEXT NOT NULL DEFAULT '[]',
                year INTEGER,
                abstract TEXT,
                doi TEXT,
                arxiv_id TEXT,
                s2_paper_id TEXT,
                pdf_url TEXT,
                venue TEXT,
                citation_count INTEGER,
                sources_json TEXT NOT NULL DEFAULT '[]',
                source_queries_json TEXT NOT NULL DEFAULT '[]',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS source_hits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id TEXT NOT NULL,
                source TEXT NOT NULL,
                query TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                FOREIGN KEY (paper_id) REFERENCES papers(paper_id)
            );

            CREATE TABLE IF NOT EXISTS merge_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id TEXT NOT NULL,
                merged_from TEXT NOT NULL,
                seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rejects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id TEXT,
                reason TEXT NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                seen_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_source_hits_paper ON source_hits(paper_id);
            CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
            CREATE INDEX IF NOT EXISTS idx_papers_arxiv ON papers(arxiv_id);
            """
        )


def _row_to_record(row: sqlite3.Row) -> PaperRecord:
    return PaperRecord(
        paper_id=row["paper_id"],
        title=row["title"],
        authors=json.loads(row["authors_json"]),
        year=row["year"],
        abstract=row["abstract"],
        doi=row["doi"],
        arxiv_id=row["arxiv_id"],
        s2_paper_id=row["s2_paper_id"],
        pdf_url=row["pdf_url"],
        venue=row["venue"],
        citation_count=row["citation_count"],
        sources=json.loads(row["sources_json"]),
        source_queries=json.loads(row["source_queries_json"]),
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
    )


def _merge_record(existing: PaperRecord, incoming: PaperRecord) -> PaperRecord:
    sources = sorted(set(existing.sources + incoming.sources))
    queries = list(dict.fromkeys(existing.source_queries + incoming.source_queries))
    authors = existing.authors if len(existing.authors) >= len(incoming.authors) else incoming.authors
    return PaperRecord(
        paper_id=existing.paper_id,
        title=existing.title or incoming.title,
        authors=authors,
        year=existing.year or incoming.year,
        abstract=(existing.abstract or incoming.abstract),
        doi=existing.doi or incoming.doi,
        arxiv_id=existing.arxiv_id or incoming.arxiv_id,
        s2_paper_id=existing.s2_paper_id or incoming.s2_paper_id,
        pdf_url=existing.pdf_url or incoming.pdf_url,
        venue=existing.venue or incoming.venue,
        citation_count=existing.citation_count or incoming.citation_count,
        sources=sources,
        source_queries=queries,
        first_seen_at=existing.first_seen_at,
        last_seen_at=incoming.last_seen_at,
    )


def upsert_papers_batch(
    records: list[PaperRecord],
    *,
    batch_size: int = 50,
    db_path: Path | None = None,
) -> dict[str, int]:
    """
    Upsert papers in chunked transactions.

    Returns counts: inserted, updated, source_hits.
    """
    if not records:
        return {"inserted": 0, "updated": 0, "source_hits": 0}

    init_db(db_path)
    inserted = 0
    updated = 0
    source_hits = 0
    now = _utc_now_iso()

    with _connect(db_path) as conn:
        for start in range(0, len(records), batch_size):
            batch = records[start : start + batch_size]
            try:
                for record in batch:
                    row = conn.execute(
                        "SELECT * FROM papers WHERE paper_id = ?",
                        (record.paper_id,),
                    ).fetchone()
                    if row is None:
                        conn.execute(
                            """
                            INSERT INTO papers (
                                paper_id, title, authors_json, year, abstract,
                                doi, arxiv_id, s2_paper_id, pdf_url, venue,
                                citation_count, sources_json, source_queries_json,
                                first_seen_at, last_seen_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                record.paper_id,
                                record.title,
                                json.dumps(record.authors),
                                record.year,
                                record.abstract,
                                record.doi,
                                record.arxiv_id,
                                record.s2_paper_id,
                                record.pdf_url,
                                record.venue,
                                record.citation_count,
                                json.dumps(record.sources),
                                json.dumps(record.source_queries),
                                record.first_seen_at,
                                record.last_seen_at,
                            ),
                        )
                        inserted += 1
                    else:
                        merged = _merge_record(_row_to_record(row), record)
                        conn.execute(
                            """
                            UPDATE papers SET
                                title = ?, authors_json = ?, year = ?, abstract = ?,
                                doi = ?, arxiv_id = ?, s2_paper_id = ?, pdf_url = ?,
                                venue = ?, citation_count = ?, sources_json = ?,
                                source_queries_json = ?, last_seen_at = ?
                            WHERE paper_id = ?
                            """,
                            (
                                merged.title,
                                json.dumps(merged.authors),
                                merged.year,
                                merged.abstract,
                                merged.doi,
                                merged.arxiv_id,
                                merged.s2_paper_id,
                                merged.pdf_url,
                                merged.venue,
                                merged.citation_count,
                                json.dumps(merged.sources),
                                json.dumps(merged.source_queries),
                                now,
                                merged.paper_id,
                            ),
                        )
                        updated += 1

                    for source in record.sources:
                        for query in record.source_queries or [""]:
                            conn.execute(
                                """
                                INSERT INTO source_hits (paper_id, source, query, seen_at)
                                VALUES (?, ?, ?, ?)
                                """,
                                (record.paper_id, source, query, now),
                            )
                            source_hits += 1
                conn.commit()
            except sqlite3.Error:
                conn.rollback()
                continue

    return {"inserted": inserted, "updated": updated, "source_hits": source_hits}


def record_reject(
    paper_id: str | None,
    reason: str,
    evidence: dict[str, Any] | None = None,
    *,
    db_path: Path | None = None,
) -> None:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO rejects (paper_id, reason, evidence_json, seen_at)
            VALUES (?, ?, ?, ?)
            """,
            (paper_id, reason, json.dumps(evidence or {}), _utc_now_iso()),
        )
        conn.commit()


def get_all_papers(db_path: Path | None = None) -> list[PaperRecord]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM papers ORDER BY last_seen_at DESC").fetchall()
    return [_row_to_record(row) for row in rows]
