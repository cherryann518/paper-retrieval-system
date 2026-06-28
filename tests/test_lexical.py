"""Tests for lexical scoring."""

from src.lexical import score_lexical_v1


def test_lexical_prefers_title_keyword_overlap():
    paper = {
        "title": "Retrieval Augmented Generation for NLP",
        "abstract": "unrelated ecology study",
        "year": 2020,
        "externalIds": {"DOI": "10.1/test"},
        "citation_count": 100,
    }
    result = score_lexical_v1(
        "retrieval augmented generation",
        paper,
        from_year=2020,
        to_year=2026,
    )
    assert result["lexical_v1"] > 0.3
    assert result["title_keyword_overlap"] > result["abstract_keyword_overlap"]
    assert result["identifier_score"] == 1.0


def test_lexical_components_sum_to_score():
    paper = {
        "title": "Neural machine translation",
        "abstract": "sequence models",
        "year": 2024,
        "citation_count": 50,
    }
    result = score_lexical_v1("machine translation", paper, from_year=2020, to_year=2026)
    assert 0.0 <= result["lexical_v1"] <= 1.0
    assert "query_phrase_match" in result
