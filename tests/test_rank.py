"""Tests for ranking."""

import pytest

from src.rank import rank_papers, rank_recency, rank_sbert, rank_tfidf


def test_rank_tfidf_orders_by_relevance(sample_paper_dicts):
    scores = rank_tfidf("retrieval augmented generation", sample_paper_dicts)
    assert len(scores) == 3
    ranked = rank_papers(
        "retrieval augmented generation",
        sample_paper_dicts,
        methods=["tfidf"],
        primary_method="tfidf",
    )
    assert ranked[0]["title"].startswith("Retrieval-Augmented")
    assert ranked[0]["rank_method"] == "tfidf_cosine"
    assert ranked[0]["relevance_score"] == ranked[0]["scores"]["tfidf_cosine"]
    assert ranked[0]["relevance_score"] >= ranked[1]["relevance_score"]


def test_rank_recency_prefers_newer_papers(sample_paper_dicts):
    scores = rank_recency(sample_paper_dicts, from_year=2020, to_year=2026)
    by_title = {p["title"]: scores[id(p)] for p in sample_paper_dicts}
    assert by_title["Recent Transformer Survey"] > by_title[
        "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
    ]
    ranked = rank_papers(
        "anything",
        sample_paper_dicts,
        methods=["recency"],
        primary_method="recency",
        from_year=2020,
        to_year=2026,
    )
    assert ranked[0]["year"] == 2025


def test_rank_papers_computes_all_metrics(sample_paper_dicts):
    ranked = rank_papers(
        "retrieval augmented generation",
        sample_paper_dicts,
        methods=["tfidf", "recency"],
        primary_method="tfidf",
    )
    assert "tfidf_cosine" in ranked[0]["scores"]
    assert "recency" in ranked[0]["scores"]
    assert "sbert_cosine" not in ranked[0]["scores"]


def test_rank_papers_empty_query_raises(sample_paper_dicts):
    with pytest.raises(ValueError, match="non-empty"):
        rank_papers("", sample_paper_dicts)


@pytest.mark.slow
def test_rank_sbert_returns_scores(sample_paper_dicts):
    scores = rank_sbert("retrieval augmented generation", sample_paper_dicts[:2])
    assert len(scores) == 2
    assert all(isinstance(value, float) for value in scores.values())
