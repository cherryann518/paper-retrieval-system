"""
Canonical paper schema shared across sources, store, and ranking.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_title(title: str | None) -> str:
    return " ".join((title or "").lower().split())


def title_fingerprint(title: str | None, year: int | None = None) -> str:
    base = normalize_title(title)
    if year is not None:
        base = f"{base}|{year}"
    return hashlib.sha256(base.encode()).hexdigest()[:16]


def paper_id_from_ids(
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
    openalex_id: str | None = None,
    s2_paper_id: str | None = None,
    title: str | None = None,
    year: int | None = None,
) -> str:
    """Stable identity: DOI → arXiv → OpenAlex → S2 paperId → title fingerprint."""
    if doi:
        cleaned = doi.lower().strip()
        cleaned = re.sub(r"^https?://doi\.org/", "", cleaned)
        return f"doi:{cleaned}"
    if arxiv_id:
        cleaned = re.sub(r"v\d+$", "", arxiv_id.lower().strip())
        return f"arxiv:{cleaned}"
    if openalex_id:
        cleaned = openalex_id.strip()
        cleaned = re.sub(r"^https?://openalex\.org/", "", cleaned, flags=re.IGNORECASE)
        return f"openalex:{cleaned.upper()}"
    if s2_paper_id:
        return f"s2:{s2_paper_id.strip()}"
    return f"fp:{title_fingerprint(title, year)}"


@dataclass
class PaperRecord:
    paper_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    abstract: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    openalex_id: str | None = None
    s2_paper_id: str | None = None
    pdf_url: str | None = None
    venue: str | None = None
    citation_count: int | None = None
    sources: list[str] = field(default_factory=list)
    source_queries: list[str] = field(default_factory=list)
    first_seen_at: str = field(default_factory=_utc_now_iso)
    last_seen_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_paper_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "abstract": self.abstract,
            "externalIds": {
                "DOI": self.doi,
                "arXiv": self.arxiv_id,
                "OpenAlex": self.openalex_id,
            },
            "openalex_id": self.openalex_id,
            "s2_paper_id": self.s2_paper_id,
            "pdf_url": self.pdf_url,
            "venue": self.venue,
            "citation_count": self.citation_count,
            "sources": list(self.sources),
            "source_queries": list(self.source_queries),
        }

    to_agent_dict = to_paper_dict


def paper_dedupe_key(paper: dict[str, Any]) -> str:
    """In-run dedupe key — same priority as paper_id_from_ids (E1)."""
    from src.identifiers import canonical_paper_id_from_dict

    return canonical_paper_id_from_dict(paper)


def dedupe_papers(papers: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for paper in papers:
        key = paper_dedupe_key(paper)
        if key in seen:
            continue
        seen.add(key)
        unique.append(paper)
    return unique
