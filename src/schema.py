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
    s2_paper_id: str | None = None,
    title: str | None = None,
    year: int | None = None,
) -> str:
    """Stable identity: DOI → arXiv → S2 paperId → title fingerprint."""
    if doi:
        return f"doi:{doi.lower().strip()}"
    if arxiv_id:
        cleaned = re.sub(r"v\d+$", "", arxiv_id.lower().strip())
        return f"arxiv:{cleaned}"
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

    def to_agent_dict(self) -> dict[str, Any]:
        """Convert to legacy agent/UI dict shape with externalIds."""
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "abstract": self.abstract,
            "externalIds": {
                "DOI": self.doi,
                "arXiv": self.arxiv_id,
            },
            "s2_paper_id": self.s2_paper_id,
            "pdf_url": self.pdf_url,
            "venue": self.venue,
            "citation_count": self.citation_count,
            "sources": list(self.sources),
            "source_queries": list(self.source_queries),
        }

    @classmethod
    def from_agent_dict(cls, paper: dict[str, Any]) -> PaperRecord:
        ids = paper.get("externalIds") or {}
        doi = paper.get("doi") or ids.get("DOI")
        arxiv_id = paper.get("arxiv_id") or ids.get("arXiv")
        s2_paper_id = paper.get("s2_paper_id")
        title = paper.get("title") or ""
        year = paper.get("year")
        return cls(
            paper_id=paper.get("paper_id")
            or paper_id_from_ids(
                doi=doi,
                arxiv_id=arxiv_id,
                s2_paper_id=s2_paper_id,
                title=title,
                year=year,
            ),
            title=title,
            authors=list(paper.get("authors") or []),
            year=year,
            abstract=paper.get("abstract"),
            doi=doi,
            arxiv_id=arxiv_id,
            s2_paper_id=s2_paper_id,
            pdf_url=paper.get("pdf_url"),
            venue=paper.get("venue"),
            citation_count=paper.get("citation_count"),
            sources=list(paper.get("sources") or []),
            source_queries=list(paper.get("source_queries") or []),
            first_seen_at=paper.get("first_seen_at") or _utc_now_iso(),
            last_seen_at=paper.get("last_seen_at") or _utc_now_iso(),
        )


def agent_paper_key(paper: dict[str, Any]) -> str:
    """Dedupe key for in-run agent pool (DOI → arXiv → title)."""
    ids = paper.get("externalIds") or {}
    if ids.get("DOI"):
        return f"doi:{ids['DOI'].lower()}"
    if ids.get("arXiv"):
        return f"arxiv:{ids['arXiv'].lower()}"
    if paper.get("paper_id"):
        return paper["paper_id"]
    return f"title:{normalize_title(paper.get('title'))}"
