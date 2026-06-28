"""Tests for NDJSON corpus export."""

import json

from src.export import export_corpus_ndjson, paper_to_ndjson_record


def test_paper_to_ndjson_record():
    paper = {
        "paper_id": "doi:10.1/x",
        "title": "Test",
        "authors": ["A"],
        "year": 2024,
        "abstract": "An abstract.",
        "externalIds": {"DOI": "10.1/x", "arXiv": "2401.00001"},
        "relevance_score": 0.8,
        "lexical_score": 0.5,
        "scores": {"sbert_cosine": 0.8, "lexical_v1": 0.5},
        "sources": ["semantic_scholar"],
    }
    row = paper_to_ndjson_record(paper, query="rag")
    assert row["doi"] == "10.1/x"
    assert row["query"] == "rag"
    assert row["scores"]["sbert_cosine"] == 0.8


def test_export_corpus_ndjson(tmp_path):
    result = {
        "query": "rag",
        "papers": [
            {
                "title": "Paper One",
                "paper_id": "doi:10.1/a",
                "externalIds": {"DOI": "10.1/a"},
                "relevance_score": 0.9,
            }
        ],
    }
    path = tmp_path / "out.ndjson"
    export_corpus_ndjson(result, path)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["title"] == "Paper One"
