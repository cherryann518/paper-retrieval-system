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
from src.fuzzy_dedupe import flag_fuzzy_duplicates, normalize_fuzzy_title
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
        "ALTER TABLE papers ADD COLUMN title_normalized TEXT",
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
                title_normalized TEXT,
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

            CREATE TABLE IF NOT EXISTS possible_duplicates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id_a TEXT NOT NULL,
                paper_id_b TEXT NOT NULL,
                match_type TEXT NOT NULL DEFAULT 'fuzzy_title_year',
                score REAL NOT NULL DEFAULT 1.0,
                seen_at TEXT NOT NULL,
                UNIQUE(paper_id_a, paper_id_b, match_type)
            );
            CREATE INDEX IF NOT EXISTS idx_possible_duplicates_a
                ON possible_duplicates(paper_id_a);
            CREATE INDEX IF NOT EXISTS idx_possible_duplicates_b
                ON possible_duplicates(paper_id_b);
            """
        )
        _migrate_schema(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_papers_openalex ON papers(openalex_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_papers_title_normalized ON papers(title_normalized)"
        )
        _ensure_fts(conn)
        _backfill_title_normalized(conn)
        conn.commit()


def _ensure_fts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
            paper_id UNINDEXED,
            title,
            abstract,
            tokenize='porter unicode61'
        )
        """
    )
    row = conn.execute("SELECT COUNT(*) AS n FROM papers_fts").fetchone()
    if row and row["n"] == 0:
        paper_count = conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()
        if paper_count and paper_count["n"] > 0:
            rebuild_fts_index(conn)


def rebuild_fts_index(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM papers_fts")
    rows = conn.execute("SELECT paper_id, title, abstract FROM papers").fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO papers_fts(paper_id, title, abstract) VALUES (?, ?, ?)",
            (row["paper_id"], row["title"] or "", row["abstract"] or ""),
        )


def _backfill_title_normalized(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT paper_id, title FROM papers WHERE title_normalized IS NULL OR title_normalized = ''"
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE papers SET title_normalized = ? WHERE paper_id = ?",
            (normalize_fuzzy_title(row["title"]), row["paper_id"]),
        )


def _sync_fts(
    conn: sqlite3.Connection,
    paper_id: str,
    title: str,
    abstract: str | None,
) -> None:
    conn.execute("DELETE FROM papers_fts WHERE paper_id = ?", (paper_id,))
    conn.execute(
        "INSERT INTO papers_fts(paper_id, title, abstract) VALUES (?, ?, ?)",
        (paper_id, title or "", abstract or ""),
    )


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
    fuzzy_dedupe_enabled: bool = True,
) -> dict[str, int]:
    if not records:
        return {
            "inserted": 0,
            "updated": 0,
            "source_hits": 0,
            "merged_by_identifier": 0,
            "possible_duplicates_flagged": 0,
        }

    init_db(db_path)
    inserted = 0
    updated = 0
    source_hits = 0
    merged_by_identifier = 0
    possible_duplicates_flagged = 0
    now = _utc_now_iso()
    fuzzy_enabled = fuzzy_dedupe_enabled

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
                    title_norm = normalize_fuzzy_title(record.title)
                    if row is None:
                        conn.execute(
                            """
                            INSERT INTO papers (
                                paper_id, title, title_normalized, authors_json, year, abstract,
                                doi, arxiv_id, openalex_id, s2_paper_id, pdf_url, venue,
                                citation_count, sources_json, source_queries_json,
                                first_seen_at, last_seen_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                record.paper_id,
                                record.title,
                                title_norm,
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
                        title_norm = normalize_fuzzy_title(merged.title)
                        conn.execute(
                            """
                            UPDATE papers SET
                                title = ?, title_normalized = ?, authors_json = ?, year = ?,
                                abstract = ?, doi = ?, arxiv_id = ?, openalex_id = ?,
                                s2_paper_id = ?, pdf_url = ?, venue = ?, citation_count = ?,
                                sources_json = ?, source_queries_json = ?, last_seen_at = ?
                            WHERE paper_id = ?
                            """,
                            (
                                merged.title,
                                title_norm,
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
                        record = merged

                    _upsert_identifiers(conn, record.paper_id, record)
                    _sync_fts(conn, record.paper_id, record.title, record.abstract)

                    if fuzzy_enabled:
                        possible_duplicates_flagged += flag_fuzzy_duplicates(
                            conn, record, now=now
                        )

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
        "possible_duplicates_flagged": possible_duplicates_flagged,
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


def search_corpus_fts(
    query: str,
    *,
    limit: int = 50,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """G4 — cross-query corpus pre-fetch via FTS5 title+abstract search."""
    import re

    init_db(db_path)
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    tokens = [t for t in tokens if len(t) > 2]
    if not tokens:
        return []

    fts_query = " OR ".join(tokens)
    with _connect(db_path) as conn:
        try:
            rows = conn.execute(
                """
                SELECT p.* FROM papers_fts f
                JOIN papers p ON p.paper_id = f.paper_id
                WHERE papers_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [_row_to_record(row).to_paper_dict() for row in rows]


def count_possible_duplicates(*, db_path: Path | None = None) -> int:
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM possible_duplicates").fetchone()
    return int(row["n"]) if row else 0


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
