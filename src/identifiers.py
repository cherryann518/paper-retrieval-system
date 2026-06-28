"""
Paper identifier normalization for dedupe and cross-run merge (E1–E3).
"""

from __future__ import annotations

import re

from src.schema import PaperRecord, paper_id_from_ids


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    cleaned = doi.strip().lower()
    cleaned = re.sub(r"^https?://doi\.org/", "", cleaned)
    return cleaned or None


def normalize_arxiv_id(arxiv_id: str | None) -> str | None:
    if not arxiv_id:
        return None
    cleaned = arxiv_id.strip().lower()
    cleaned = re.sub(r"^https?://arxiv\.org/abs/", "", cleaned)
    cleaned = re.sub(r"v\d+$", "", cleaned)
    return cleaned or None


def normalize_openalex_id(openalex_id: str | None) -> str | None:
    if not openalex_id:
        return None
    cleaned = openalex_id.strip()
    cleaned = re.sub(r"^https?://openalex\.org/", "", cleaned, flags=re.IGNORECASE)
    return cleaned.upper() if cleaned else None


def normalize_s2_id(s2_paper_id: str | None) -> str | None:
    if not s2_paper_id:
        return None
    return s2_paper_id.strip() or None


def identifiers_for_record(record: PaperRecord) -> list[tuple[str, str]]:
    """All known external ids for a record, as (id_type, id_normalized) pairs."""
    pairs: list[tuple[str, str]] = []
    doi = normalize_doi(record.doi)
    if doi:
        pairs.append(("doi", doi))
    arxiv = normalize_arxiv_id(record.arxiv_id)
    if arxiv:
        pairs.append(("arxiv", arxiv))
    oa = normalize_openalex_id(record.openalex_id)
    if oa:
        pairs.append(("openalex", oa))
    s2 = normalize_s2_id(record.s2_paper_id)
    if s2:
        pairs.append(("s2", s2))
    return pairs


def canonical_paper_id_from_dict(paper: dict) -> str:
    """In-run dedupe key aligned with paper_id_from_ids (E1)."""
    ids = paper.get("externalIds") or {}
    return paper_id_from_ids(
        doi=ids.get("DOI") or paper.get("doi"),
        arxiv_id=ids.get("arXiv") or paper.get("arxiv_id"),
        openalex_id=ids.get("OpenAlex") or paper.get("openalex_id"),
        s2_paper_id=paper.get("s2_paper_id"),
        title=paper.get("title"),
        year=paper.get("year"),
    )
