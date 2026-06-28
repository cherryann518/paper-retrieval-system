"""Tests for 1st-baseline retrieval (mocked fetch)."""

from __future__ import annotations

import pytest

from src.fetch import FetchStats, SurveyConfig
from src.pipeline import run_retrieval
from src.schema import dedupe_papers


def test_dedupe_papers_by_doi():
    papers = [
        {"title": "A", "externalIds": {"DOI": "10.1/a"}},
        {"title": "A duplicate", "externalIds": {"DOI": "10.1/a"}},
        {"title": "B", "externalIds": {"DOI": "10.1/b"}},
    ]
    assert len(dedupe_papers(papers)) == 2


def test_run_retrieval_mocked(sample_records, monkeypatch):
    def mock_fetch_all_sources(query, config, offset=0, limit=None):
        return sample_records, FetchStats(api_calls=2, cache_hits=0)

    monkeypatch.setattr("src.pipeline.fetch_all_sources", mock_fetch_all_sources)
    monkeypatch.setattr(
        "src.pipeline.upsert_papers_batch",
        lambda records, **kw: {"inserted": len(records), "updated": 0, "source_hits": len(records)},
    )
    monkeypatch.setattr("src.pipeline.load_local_corpus_for_query", lambda *a, **k: [])
    monkeypatch.setattr("src.pipeline.record_screening_batch", lambda *a, **k: None)

    config = SurveyConfig(
        sources=["semantic_scholar", "arxiv"],
        rank_method="sbert",
        min_relevance_score=0.0,
        display_limit=10,
    )
    result = run_retrieval(
        "retrieval augmented generation",
        survey_config=config,
        use_local_corpus=False,
    )

    assert result["status"] in ("ok", "partial_success")
    assert len(result["papers_display"]) <= 10
    assert len(result["papers"]) >= len(result["papers_display"])
    assert result["metrics"]["api_calls"] == 2
    assert result["search_query"] == "retrieval augmented generation"


def test_run_retrieval_empty_query_raises():
    with pytest.raises(ValueError, match="non-empty"):
        run_retrieval("   ")
