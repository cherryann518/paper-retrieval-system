"""
SQLite main database for canonical paper storage, identifiers, and query state.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import PAPERS_DB_PATH
from src.identifiers import identifiers_for_record
from src.schema import PaperRecord


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or PAPERS_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    for ddl in (
        "ALTER TABLE papers ADD COLUMN openalex_id TEXT",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass


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
                openalex_id TEXT,
                s2_paper_id TEXT,
                pdf_url TEXT,
                venue TEXT,
                citation_count INTEGER,
                sources_json TEXT NOT NULL DEFAULT '[]',
                source_queries_json TEXT NOT NULL DEFAULT '[]',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_identifiers (
                id_type TEXT NOT NULL,
                id_normalized TEXT NOT NULL,
                paper_id TEXT NOT NULL,
                PRIMARY KEY (id_type, id_normalized),
                FOREIGN KEY (paper_id) REFERENCES papers(paper_id)
            );
            CREATE INDEX IF NOT EXISTS idx_paper_identifiers_paper
                ON paper_identifiers(paper_id);
            CREATE TABLE IF NOT EXISTS source_hits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id TEXT NOT NULL,
                source TEXT NOT NULL,
                query TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                FOREIGN KEY (paper_id) REFERENCES papers(paper_id)
            );
            CREATE INDEX IF NOT EXISTS idx_source_hits_query ON source_hits(query);
            CREATE INDEX IF NOT EXISTS idx_source_hits_paper ON source_hits(paper_id);
            CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
            CREATE INDEX IF NOT EXISTS idx_papers_arxiv ON papers(arxiv_id);

            CREATE TABLE IF NOT EXISTS screening_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id TEXT,
                query TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                relevance_score REAL,
                seen_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_screening_query ON screening_decisions(query);

            CREATE TABLE IF NOT EXISTS query_state (
                query TEXT PRIMARY KEY,
                last_run_at TEXT NOT NULL,
                accepted_count INTEGER NOT NULL DEFAULT 0,
                rejected_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                consecutive_zero_accept INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        _migrate_schema(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_papers_openalex ON papers(openalex_id)"
        )
        conn.commit()


def _row_to_record(row: sqlite3.Row) -> PaperRecord:
    keys = row.keys()
    return PaperRecord(
        paper_id=row["paper_id"],
        title=row["title"],
        authors=json.loads(row["authors_json"]),
        year=row["year"],
        abstract=row["abstract"],
        doi=row["doi"],
        arxiv_id=row["arxiv_id"],
        openalex_id=row["openalex_id"] if "openalex_id" in keys else None,
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
        abstract=existing.abstract or incoming.abstract,
        doi=existing.doi or incoming.doi,
        arxiv_id=existing.arxiv_id or incoming.arxiv_id,
        openalex_id=existing.openalex_id or incoming.openalex_id,
        s2_paper_id=existing.s2_paper_id or incoming.s2_paper_id,
        pdf_url=existing.pdf_url or incoming.pdf_url,
        venue=existing.venue or incoming.venue,
        citation_count=existing.citation_count or incoming.citation_count,
        sources=sources,
        source_queries=queries,
        first_seen_at=existing.first_seen_at,
        last_seen_at=incoming.last_seen_at,
    )


def _resolve_paper_id(conn: sqlite3.Connection, record: PaperRecord) -> str:
    """E3: merge on identifier lookup before insert."""
    for id_type, id_norm in identifiers_for_record(record):
        row = conn.execute(
            """
            SELECT paper_id FROM paper_identifiers
            WHERE id_type = ? AND id_normalized = ?
            """,
            (id_type, id_norm),
        ).fetchone()
        if row is not None:
            return row["paper_id"]
    row = conn.execute(
        "SELECT paper_id FROM papers WHERE paper_id = ?",
        (record.paper_id,),
    ).fetchone()
    if row is not None:
        return row["paper_id"]
    return record.paper_id


def _upsert_identifiers(conn: sqlite3.Connection, paper_id: str, record: PaperRecord) -> None:
    for id_type, id_norm in identifiers_for_record(record):
        conn.execute(
            """
            INSERT INTO paper_identifiers (id_type, id_normalized, paper_id)
            VALUES (?, ?, ?)
            ON CONFLICT(id_type, id_normalized) DO UPDATE SET paper_id = excluded.paper_id
            """,
            (id_type, id_norm, paper_id),
        )


def upsert_papers_batch(
    records: list[PaperRecord],
    *,
    batch_size: int = 50,
    db_path: Path | None = None,
) -> dict[str, int]:
    if not records:
        return {"inserted": 0, "updated": 0, "source_hits": 0, "merged_by_identifier": 0}

    init_db(db_path)
    inserted = 0
    updated = 0
    source_hits = 0
    merged_by_identifier = 0
    now = _utc_now_iso()

    with _connect(db_path) as conn:
        for start in range(0, len(records), batch_size):
            batch = records[start : start + batch_size]
            try:
                for record in batch:
                    canonical_id = _resolve_paper_id(conn, record)
                    if canonical_id != record.paper_id:
                        merged_by_identifier += 1
                    record = PaperRecord(
                        paper_id=canonical_id,
                        title=record.title,
                        authors=record.authors,
                        year=record.year,
                        abstract=record.abstract,
                        doi=record.doi,
                        arxiv_id=record.arxiv_id,
                        openalex_id=record.openalex_id,
                        s2_paper_id=record.s2_paper_id,
                        pdf_url=record.pdf_url,
                        venue=record.venue,
                        citation_count=record.citation_count,
                        sources=record.sources,
                        source_queries=record.source_queries,
                        first_seen_at=record.first_seen_at,
                        last_seen_at=record.last_seen_at,
                    )

                    row = conn.execute(
                        "SELECT * FROM papers WHERE paper_id = ?",
                        (record.paper_id,),
                    ).fetchone()
                    if row is None:
                        conn.execute(
                            """
                            INSERT INTO papers (
                                paper_id, title, authors_json, year, abstract,
                                doi, arxiv_id, openalex_id, s2_paper_id, pdf_url, venue,
                                citation_count, sources_json, source_queries_json,
                                first_seen_at, last_seen_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                record.paper_id,
                                record.title,
                                json.dumps(record.authors),
                                record.year,
                                record.abstract,
                                record.doi,
                                record.arxiv_id,
                                record.openalex_id,
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
                                doi = ?, arxiv_id = ?, openalex_id = ?, s2_paper_id = ?,
                                pdf_url = ?, venue = ?, citation_count = ?,
                                sources_json = ?, source_queries_json = ?, last_seen_at = ?
                            WHERE paper_id = ?
                            """,
                            (
                                merged.title,
                                json.dumps(merged.authors),
                                merged.year,
                                merged.abstract,
                                merged.doi,
                                merged.arxiv_id,
                                merged.openalex_id,
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

                    _upsert_identifiers(conn, record.paper_id, record)

                    for source in record.sources:
                        for q in record.source_queries or [""]:
                            conn.execute(
                                """
                                INSERT INTO source_hits (paper_id, source, query, seen_at)
                                VALUES (?, ?, ?, ?)
                                """,
                                (record.paper_id, source, q, now),
                            )
                            source_hits += 1
                conn.commit()
            except sqlite3.Error:
                conn.rollback()
                raise

    return {
        "inserted": inserted,
        "updated": updated,
        "source_hits": source_hits,
        "merged_by_identifier": merged_by_identifier,
    }


def get_all_papers(db_path: Path | None = None) -> list[PaperRecord]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM papers ORDER BY last_seen_at DESC").fetchall()
    return [_row_to_record(row) for row in rows]


def load_local_corpus_for_query(
    query: str,
    *,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT p.* FROM papers p
            JOIN source_hits h ON h.paper_id = p.paper_id
            WHERE h.query = ?
            ORDER BY p.last_seen_at DESC
            """,
            (query.strip(),),
        ).fetchall()
    return [_row_to_record(row).to_paper_dict() for row in rows]


def record_screening_batch(
    query: str,
    accepted: list[dict[str, Any]],
    rejects: list[dict[str, Any]],
    *,
    db_path: Path | None = None,
) -> None:
    init_db(db_path)
    now = _utc_now_iso()
    with _connect(db_path) as conn:
        for paper in accepted:
            conn.execute(
                """
                INSERT INTO screening_decisions (
                    paper_id, query, decision, reason, evidence_json,
                    relevance_score, seen_at
                ) VALUES (?, ?, 'accept', 'passed_screening', '{}', ?, ?)
                """,
                (paper.get("paper_id"), query, paper.get("relevance_score"), now),
            )
        for reject in rejects:
            conn.execute(
                """
                INSERT INTO screening_decisions (
                    paper_id, query, decision, reason, evidence_json,
                    relevance_score, seen_at
                ) VALUES (?, ?, 'reject', ?, ?, ?, ?)
                """,
                (
                    reject.get("paper_id"),
                    query,
                    reject.get("reason", "unknown"),
                    json.dumps(reject.get("evidence") or {}),
                    reject.get("relevance_score"),
                    now,
                ),
            )
        conn.commit()
