"""
Deterministic lexical relevance scoring.

Explainable keyword + metadata formula — always computed as a secondary score
alongside SBERT. Does not replace primary rank unless configured.
"""

from __future__ import annotations

import math
import re
from typing import Any

LEXICAL_VERSION = "baseline_lexical_v1"

_WEIGHTS = {
    "title_keyword_overlap": 0.35,
    "abstract_keyword_overlap": 0.30,
    "query_phrase_match": 0.15,
    "recency_score": 0.10,
    "identifier_score": 0.05,
    "citation_score": 0.05,
}

_STOPWORDS = frozenset(
    """
    a an the and or but in on at to for of with by from as is are was were be been
    being have has had do does did will would could should may might must shall can
    this that these those it its they their we our you your he she his her not no
    """.split()
)


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {t for t in tokens if len(t) > 1 and t not in _STOPWORDS}


def _keyword_overlap(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    doc_tokens = _tokenize(text)
    if not doc_tokens:
        return 0.0
    return len(query_tokens & doc_tokens) / len(query_tokens)


def _query_phrase_match(query: str, title: str, abstract: str) -> float:
    q = " ".join(query.lower().split())
    if not q:
        return 0.0
    title_l = (title or "").lower()
    abstract_l = (abstract or "").lower()
    if q in title_l:
        return 1.0
    if q in abstract_l:
        return 0.7
    return 0.0


def _recency_component(year: int | None, *, from_year: int, to_year: int) -> float:
    if not isinstance(year, int):
        return 0.0
    if year < from_year or year > to_year:
        return 0.0
    span = max(to_year - from_year, 1)
    return (year - from_year) / span


def _identifier_component(paper: dict[str, Any]) -> float:
    ids = paper.get("externalIds") or {}
    if ids.get("DOI") or ids.get("arXiv") or ids.get("OpenAlex"):
        return 1.0
    if paper.get("doi") or paper.get("arxiv_id") or paper.get("openalex_id"):
        return 1.0
    if paper.get("s2_paper_id"):
        return 0.5
    return 0.0


def _citation_component(citation_count: int | None) -> float:
    if not citation_count or citation_count <= 0:
        return 0.0
    return min(math.log1p(citation_count) / math.log1p(10_000), 1.0)


def score_lexical_v1(
    query: str,
    paper: dict[str, Any],
    *,
    from_year: int = 2020,
    to_year: int = 2026,
) -> dict[str, float]:
    """
    Weighted lexical score in [0, 1] plus per-component breakdown.

    Components (all in [0, 1]):
      title_keyword_overlap   — query token recall in title
      abstract_keyword_overlap — query token recall in abstract
      query_phrase_match      — full query substring in title/abstract
      recency_score           — publication year within timeline window
      identifier_score        — has DOI/arXiv/OpenAlex (partial for S2-only)
      citation_score          — log-normalized citation count
    """
    query_tokens = _tokenize(query)
    title = paper.get("title") or ""
    abstract = paper.get("abstract") or ""

    components = {
        "title_keyword_overlap": round(_keyword_overlap(query_tokens, title), 4),
        "abstract_keyword_overlap": round(_keyword_overlap(query_tokens, abstract), 4),
        "query_phrase_match": round(_query_phrase_match(query, title, abstract), 4),
        "recency_score": round(
            _recency_component(paper.get("year"), from_year=from_year, to_year=to_year),
            4,
        ),
        "identifier_score": round(_identifier_component(paper), 4),
        "citation_score": round(_citation_component(paper.get("citation_count")), 4),
    }
    total = sum(_WEIGHTS[k] * components[k] for k in _WEIGHTS)
    return {
        **components,
        "lexical_v1": round(min(max(total, 0.0), 1.0), 4),
    }


def rank_lexical(
    query: str,
    papers: list[dict[str, Any]],
    *,
    from_year: int = 2020,
    to_year: int = 2026,
) -> dict[int, float]:
    if not papers:
        return {}
    return {
        id(paper): score_lexical_v1(query, paper, from_year=from_year, to_year=to_year)[
            "lexical_v1"
        ]
        for paper in papers
    }
