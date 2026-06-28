"""Tests for query builder and screening."""

from src.fetch import SurveyConfig
from src.query_builder import build_canonical_queries
from src.screening import apply_screening


def test_build_canonical_queries_user_only():
    cfg = SurveyConfig(topic_overview="RAG", research_questions=["what is rag"])
    queries = build_canonical_queries(cfg, user_query="my topic", include_config_queries=False)
    assert queries == ["my topic"]


def test_build_canonical_queries_survey_mode():
    cfg = SurveyConfig(
        topic_overview="retrieval augmented generation",
        research_questions=["dense passage retrieval"],
        query_hints=["neural IR"],
        max_queries=10,
    )
    queries = build_canonical_queries(cfg, user_query="RAG", include_config_queries=True)
    assert queries[0] == "RAG"
    assert "dense passage retrieval" in queries
    assert "neural IR" in queries


def test_apply_screening_rejects_low_score():
    cfg = SurveyConfig(min_relevance_score=0.5)
    ranked = [
        {"title": "Good", "relevance_score": 0.8, "year": 2020},
        {"title": "Weak", "relevance_score": 0.2, "year": 2020},
        {"title": "", "relevance_score": 0.9},
    ]
    accepted, rejects = apply_screening(ranked, cfg)
    assert len(accepted) == 1
    assert len(rejects) == 2
    assert rejects[0]["reason"] == "below_min_score"
