"""Tests for multi-source fetch orchestration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.fetch import SurveyConfig, fetch_all_sources, records_to_agent_dicts


def test_survey_config_load_defaults(tmp_path):
    missing = tmp_path / "missing.json"
    cfg = SurveyConfig.load(missing)
    assert cfg.rank_method == "sbert"
    assert "semantic_scholar" in cfg.sources
    assert cfg.year_filter == "2020-2026"


def test_survey_config_load_from_file(tmp_path):
    path = tmp_path / "survey_config.json"
    path.write_text(
        json.dumps(
            {
                "topic_overview": "robotics",
                "timeline_from_year": 2022,
                "timeline_to_year": 2024,
                "sources": ["arxiv"],
                "rank_method": "tfidf",
            }
        ),
        encoding="utf-8",
    )
    cfg = SurveyConfig.load(path)
    assert cfg.topic_overview == "robotics"
    assert cfg.year_filter == "2022-2024"
    assert cfg.sources == ["arxiv"]
    assert cfg.rank_method == "tfidf"


def test_fetch_all_sources_merges_mocked_adapters(monkeypatch, sample_records):
    s2_raw = {
        "title": sample_records[0].title,
        "authors": sample_records[0].authors,
        "year": sample_records[0].year,
        "abstract": sample_records[0].abstract,
        "externalIds": {"DOI": sample_records[0].doi, "ArXiv": sample_records[0].arxiv_id},
    }
    arxiv_raw = {
        "arxiv_id": "1706.03762",
        "title": sample_records[1].title,
        "authors": sample_records[1].authors,
        "year": sample_records[1].year,
        "abstract": sample_records[1].abstract,
    }

    monkeypatch.setattr(
        "src.fetch.fetch_semantic_scholar_soft",
        lambda *a, **k: ([s2_raw], None, False),
    )
    monkeypatch.setattr(
        "src.fetch.fetch_arxiv_soft",
        lambda *a, **k: ([arxiv_raw], None, False),
    )

    cfg = SurveyConfig(sources=["semantic_scholar", "arxiv"])
    records, stats = fetch_all_sources("rag", cfg)

    assert len(records) == 2
    assert stats.api_calls == 2
    assert stats.cache_hits == 0
    assert stats.api_calls_by_source["semantic_scholar"] == 1
    assert stats.api_calls_by_source["arxiv"] == 1
    assert stats.papers_fetched_by_source["semantic_scholar"] == 1
    assert stats.papers_fetched_by_source["arxiv"] == 1

    agent_dicts = records_to_agent_dicts(records)
    assert agent_dicts[0]["externalIds"]["DOI"] == "10.5555/123"


def test_fetch_all_sources_records_errors(monkeypatch):
    monkeypatch.setattr(
        "src.fetch.fetch_semantic_scholar_soft",
        lambda *a, **k: ([], "HTTP 503", False),
    )
    monkeypatch.setattr(
        "src.fetch.fetch_arxiv_soft",
        lambda *a, **k: ([], None, True),
    )

    records, stats = fetch_all_sources(
        "test",
        SurveyConfig(sources=["semantic_scholar", "arxiv"]),
    )

    assert records == []
    assert stats.api_calls == 1
    assert stats.cache_hits == 1
    assert len(stats.fetch_errors) == 1
    assert stats.fetch_errors[0]["source"] == "semantic_scholar"


def test_fetch_respects_max_candidates(monkeypatch):
    many = [
        {
            "title": f"Paper {i}",
            "authors": [],
            "year": 2020,
            "abstract": "x",
            "externalIds": {"DOI": f"10.1/{i}"},
        }
        for i in range(50)
    ]

    monkeypatch.setattr(
        "src.fetch.fetch_semantic_scholar_soft",
        lambda *a, **k: (many, None, False),
    )
    monkeypatch.setattr(
        "src.fetch.fetch_arxiv_soft",
        lambda *a, **k: (many, None, False),
    )

    cfg = SurveyConfig(sources=["semantic_scholar", "arxiv"], max_candidates_per_run=10)
    records, _ = fetch_all_sources("test", cfg)
    assert len(records) == 10
