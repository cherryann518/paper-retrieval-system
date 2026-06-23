"""
Normalize raw source records into canonical PaperRecord objects.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from src.schema import PaperRecord, paper_id_from_ids


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_arxiv_id(arxiv_id: str | None) -> str | None:
    if not arxiv_id:
        return None
    cleaned = arxiv_id.strip()
    cleaned = re.sub(r"^https?://arxiv\.org/abs/", "", cleaned)
    cleaned = re.sub(r"v\d+$", "", cleaned, flags=re.IGNORECASE)
    return cleaned or None


def normalize_s2(raw: dict[str, Any], *, source_query: str = "") -> PaperRecord | None:
    title = (raw.get("title") or "").strip()
    if not title:
        return None

    ids = raw.get("externalIds") or {}
    doi = ids.get("DOI")
    arxiv_id = _clean_arxiv_id(ids.get("arXiv"))
    s2_paper_id = raw.get("paperId")
    year = raw.get("year")
    if isinstance(year, str) and year.isdigit():
        year = int(year)

    oa_pdf = raw.get("openAccessPdf") or {}
    pdf_url = raw.get("pdf_url")
    if not pdf_url and isinstance(oa_pdf, dict):
        pdf_url = oa_pdf.get("url")

    paper_id = paper_id_from_ids(
        doi=doi,
        arxiv_id=arxiv_id,
        s2_paper_id=s2_paper_id,
        title=title,
        year=year,
    )
    now = _utc_now_iso()
    return PaperRecord(
        paper_id=paper_id,
        title=title,
        authors=list(raw.get("authors") or []),
        year=year,
        abstract=raw.get("abstract"),
        doi=doi,
        arxiv_id=arxiv_id,
        s2_paper_id=s2_paper_id,
        pdf_url=pdf_url,
        venue=raw.get("venue"),
        citation_count=raw.get("citationCount"),
        sources=["semantic_scholar"],
        source_queries=[source_query] if source_query else [],
        first_seen_at=now,
        last_seen_at=now,
    )


def normalize_arxiv(raw: dict[str, Any], *, source_query: str = "") -> PaperRecord | None:
    title = (raw.get("title") or "").strip()
    if not title:
        return None

    arxiv_id = _clean_arxiv_id(raw.get("arxiv_id"))
    year = raw.get("year")
    paper_id = paper_id_from_ids(arxiv_id=arxiv_id, title=title, year=year)
    now = _utc_now_iso()
    return PaperRecord(
        paper_id=paper_id,
        title=title,
        authors=list(raw.get("authors") or []),
        year=year,
        abstract=raw.get("abstract"),
        arxiv_id=arxiv_id,
        pdf_url=raw.get("pdf_url"),
        venue=raw.get("primary_category"),
        sources=["arxiv"],
        source_queries=[source_query] if source_query else [],
        first_seen_at=now,
        last_seen_at=now,
    )


def merge_paper_records(records: list[PaperRecord]) -> list[PaperRecord]:
    """Merge records by paper_id, combining sources and source_queries."""
    merged: dict[str, PaperRecord] = {}
    for record in records:
        existing = merged.get(record.paper_id)
        if existing is None:
            merged[record.paper_id] = record
            continue
        sources = sorted(set(existing.sources + record.sources))
        queries = list(dict.fromkeys(existing.source_queries + record.source_queries))
        merged[record.paper_id] = PaperRecord(
            paper_id=existing.paper_id,
            title=existing.title or record.title,
            authors=existing.authors or record.authors,
            year=existing.year or record.year,
            abstract=existing.abstract or record.abstract,
            doi=existing.doi or record.doi,
            arxiv_id=existing.arxiv_id or record.arxiv_id,
            s2_paper_id=existing.s2_paper_id or record.s2_paper_id,
            pdf_url=existing.pdf_url or record.pdf_url,
            venue=existing.venue or record.venue,
            citation_count=existing.citation_count or record.citation_count,
            sources=sources,
            source_queries=queries,
            first_seen_at=existing.first_seen_at,
            last_seen_at=record.last_seen_at,
        )
    return list(merged.values())
