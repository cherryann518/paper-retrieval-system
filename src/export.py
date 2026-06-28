"""
Corpus export for downstream RAG ingest (NDJSON).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def paper_to_ndjson_record(paper: dict[str, Any], *, query: str = "") -> dict[str, Any]:
    ids = paper.get("externalIds") or {}
    return {
        "paper_id": paper.get("paper_id"),
        "title": paper.get("title"),
        "authors": paper.get("authors") or [],
        "year": paper.get("year"),
        "abstract": paper.get("abstract"),
        "doi": ids.get("DOI") or paper.get("doi"),
        "arxiv_id": ids.get("arXiv") or paper.get("arxiv_id"),
        "openalex_id": paper.get("openalex_id"),
        "s2_paper_id": paper.get("s2_paper_id"),
        "pdf_url": paper.get("pdf_url"),
        "venue": paper.get("venue"),
        "citation_count": paper.get("citation_count"),
        "sources": paper.get("sources") or [],
        "source_queries": paper.get("source_queries") or [],
        "relevance_score": paper.get("relevance_score"),
        "lexical_score": paper.get("lexical_score"),
        "scores": paper.get("scores") or {},
        "lexical_components": paper.get("lexical_components") or {},
        "rank_method": paper.get("rank_method"),
        "query": query,
    }


def export_corpus_ndjson(
    result: dict[str, Any],
    path: Path,
    *,
    use_display: bool = False,
) -> Path:
    """
    Write one JSON object per line for each accepted paper in *result*.

    Default exports full accepted corpus; set use_display=True for preview slice only.
    """
    query = result.get("query") or ""
    papers = (
        result.get("papers_display") or []
        if use_display
        else result.get("papers") or []
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for paper in papers:
            handle.write(
                json.dumps(paper_to_ndjson_record(paper, query=query), ensure_ascii=False)
                + "\n"
            )
    return path
