"""Tests for eval helpers."""

import json
from pathlib import Path

import pytest

from src.eval import check_targets, check_targets_full, load_benchmark


def test_check_targets_finds_doi_in_top10():
    papers = [
        {
            "title": "Target Paper",
            "externalIds": {"DOI": "10.1/target"},
        },
        {
            "title": "Other",
            "externalIds": {"DOI": "10.1/other"},
        },
    ]
    targets = [{"title": "Target Paper", "doi": "10.1/target"}]
    result = check_targets(papers, papers, targets)
    assert result["configured"] == 1
    assert result["found_in_top10"] == 1
    assert result["found_in_pool"] == 1
    assert result["details"][0]["rank_top10"] == 1


def test_check_targets_pool_but_not_top10():
    pool = [
        {"title": "First", "externalIds": {}},
        {"title": "Target", "externalIds": {"arXiv": "1706.03762"}},
    ]
    top10 = [pool[0]]
    targets = [{"title": "Target", "arxiv": "1706.03762"}]
    result = check_targets(top10, pool, targets)
    assert result["found_in_top10"] == 0
    assert result["found_in_pool"] == 1
    assert result["details"][0]["rank_pool"] == 2


def test_check_targets_empty():
    result = check_targets([], [], [])
    assert result["configured"] == 0
    assert result["found_in_top10"] == 0


def test_check_targets_full_separates_pool_and_accepted():
    target = {"title": "Target Paper", "doi": "10.1/target"}
    pool = [
        {"title": "Target Paper", "externalIds": {"DOI": "10.1/target"}, "relevance_score": 0.3},
        {"title": "Other", "externalIds": {}, "relevance_score": 0.9},
    ]
    accepted = [pool[1]]
    rejects = [
        {
            "title": "Target Paper",
            "paper_id": "doi:10.1/target",
            "relevance_score": 0.3,
            "reason": "below_min_score",
        }
    ]
    report = check_targets_full(
        targets=[target],
        display=accepted,
        ranked_pool=pool,
        accepted=accepted,
        rejects=rejects,
    )
    assert report["ranked_pool"]["found_in_pool"] == 1
    assert report["accepted"]["found_in_pool"] == 0
    assert report["rejects"]["found_in_pool"] == 1


def test_load_benchmark(tmp_path):
    path = tmp_path / "queries.json"
    path.write_text(
        json.dumps([{"query": "test topic", "category": "short", "targets": []}]),
        encoding="utf-8",
    )
    cases = load_benchmark(path)
    assert len(cases) == 1
    assert cases[0]["query"] == "test topic"


def test_load_benchmark_invalid_raises(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(ValueError, match="array"):
        load_benchmark(path)
