"""Utility helpers for offline fixtures."""

import json

from src.config import DATA_DIR
from src.rank import embed_and_rank, rank_papers
from src.sources import (
    SemanticScholarError,
    fetch_semantic_scholar_soft,
    search_semantic_scholar,
)

__all__ = [
    "SemanticScholarError",
    "embed_and_rank",
    "fetch_semantic_scholar_soft",
    "load_sample_papers",
    "rank_papers",
    "search_papers",
    "search_semantic_scholar",
]


def load_sample_papers(limit: int | None = None) -> list[dict]:
    path = DATA_DIR / "sample_papers.json"
    with path.open(encoding="utf-8") as f:
        papers = json.load(f)
    if limit is not None:
        return papers[:limit]
    return papers


def search_papers(query: str, max_results: int = 10) -> list[dict]:
    papers, _ = search_semantic_scholar(query, limit=max_results)
    return papers
