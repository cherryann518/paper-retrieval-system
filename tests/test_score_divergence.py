"""Tests for SBERT vs lexical divergence summary."""

from src.score_divergence import score_divergence_summary


def test_score_divergence_summary_orders_by_abs_delta():
    papers = [
        {
            "title": "Low divergence",
            "scores": {"sbert_cosine": 0.8, "lexical_v1": 0.75},
        },
        {
            "title": "High divergence",
            "scores": {"sbert_cosine": 0.9, "lexical_v1": 0.2},
        },
    ]
    summary = score_divergence_summary(papers, top_n=1)
    assert summary["count"] == 2
    assert summary["top_divergent"][0]["title"] == "High divergence"
    assert summary["top_divergent"][0]["abs_delta"] == 0.7
