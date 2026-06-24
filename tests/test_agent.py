"""Tests for agent helpers and orchestration (mocked fetch)."""

from __future__ import annotations

import pytest

from src.agent import (
    _effective_topic,
    dedupe_papers,
    results_acceptable,
    run_search_agent,
)
from src.config import SCORE_GOOD, SCORE_TOP_MIN
from src.fetch import FetchStats, SurveyConfig


def test_effective_topic_expands_rag():
    assert _effective_topic("RAG") == "retrieval augmented generation"
    assert _effective_topic("multi word query") == "multi word query"


def test_dedupe_papers_by_doi():
    papers = [
        {"title": "A", "externalIds": {"DOI": "10.1/a"}},
        {"title": "A duplicate", "externalIds": {"DOI": "10.1/a"}},
        {"title": "B", "externalIds": {"DOI": "10.1/b"}},
    ]
    assert len(dedupe_papers(papers)) == 2


def test_results_acceptable_passes_strong_pool():
    ranked = [
        {"relevance_score": 0.55},
        {"relevance_score": 0.48},
        {"relevance_score": 0.44},
        {"relevance_score": 0.40},
        {"relevance_score": 0.30},
    ]
    ok, reason = results_acceptable(ranked)
    assert ok is True
    assert reason == "ok"


def test_results_acceptable_fails_low_top_score():
    ranked = [{"relevance_score": SCORE_TOP_MIN - 0.05}]
    ok, reason = results_acceptable(ranked)
    assert ok is False
    assert reason.startswith("top_score_low")


def test_results_acceptable_fails_too_few_good():
    ranked = [
        {"relevance_score": SCORE_GOOD + 0.05},
        {"relevance_score": SCORE_GOOD - 0.05},
        {"relevance_score": SCORE_GOOD - 0.05},
    ]
    ok, reason = results_acceptable(ranked)
    assert ok is False
    assert reason.startswith("too_few_good_papers")


def test_run_search_agent_single_fetch_mocked(sample_records, monkeypatch, tmp_path):
    def mock_fetch_all_sources(query, config, offset=0, limit=None):
        return sample_records, FetchStats(api_calls=2, cache_hits=0)

    def mock_rank_papers(query, papers, **kwargs):
        ranked = [
            {
                **paper,
                "relevance_score": max(0.55 - i * 0.08, 0.41),
                "scores": {"sbert_cosine": 0.55, "tfidf_cosine": 0.4, "recency": 0.5},
                "rank_method": "sbert_cosine",
            }
            for i, paper in enumerate(papers)
        ]
        while len(ranked) < 3:
            ranked.append(
                {
                    "title": f"Padding paper {len(ranked)}",
                    "relevance_score": 0.42,
                    "scores": {"sbert_cosine": 0.42, "tfidf_cosine": 0.3, "recency": 0.5},
                    "rank_method": "sbert_cosine",
                    "externalIds": {},
                }
            )
        return ranked

    monkeypatch.setattr("src.agent.fetch_all_sources", mock_fetch_all_sources)
    monkeypatch.setattr("src.agent.upsert_papers_batch", lambda records, **kw: {
        "inserted": len(records),
        "updated": 0,
        "source_hits": len(records),
    })
    monkeypatch.setattr("src.agent.rank_papers", mock_rank_papers)

    config = SurveyConfig(sources=["semantic_scholar", "arxiv"], rank_method="sbert")
    result = run_search_agent(
        "retrieval augmented generation",
        mode="single_fetch",
        survey_config=config,
        max_pages=1,
    )

    assert result["status"] == "ok"
    assert result["mode"] == "single_fetch"
    assert len(result["papers"]) <= 10
    assert result["metrics"]["api_calls"] == 2
    assert result["refinement_rounds"] == 0
    assert result["search_queries_used"] == ["retrieval augmented generation"]


def test_run_search_agent_expands_rag_acronym(sample_records, monkeypatch):
    captured_rank_topics: list[str] = []

    def mock_fetch_all_sources(query, config, offset=0, limit=None):
        return sample_records[:1], FetchStats()

    def mock_rank_papers(query, papers, **kwargs):
        captured_rank_topics.append(query)
        return [
            {
                **papers[0],
                "relevance_score": 0.55,
                "scores": {"sbert_cosine": 0.55},
                "rank_method": "sbert_cosine",
            }
        ]

    monkeypatch.setattr("src.agent.fetch_all_sources", mock_fetch_all_sources)
    monkeypatch.setattr("src.agent.upsert_papers_batch", lambda records, **kw: {
        "inserted": 1,
        "updated": 0,
        "source_hits": 1,
    })
    monkeypatch.setattr("src.agent.rank_papers", mock_rank_papers)

    result = run_search_agent("RAG", mode="single_fetch", max_pages=1)

    assert result["rank_topic"] == "retrieval augmented generation"
    assert all(topic == "retrieval augmented generation" for topic in captured_rank_topics)


def test_run_search_agent_empty_query_raises():
    with pytest.raises(ValueError, match="non-empty"):
        run_search_agent("   ")
