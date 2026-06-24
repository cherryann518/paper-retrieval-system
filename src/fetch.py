"""
Multi-source fetch orchestration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import (
    DATA_DIR,
    MAX_CANDIDATES_PER_RUN,
    SEMANTIC_SCHOLAR_FETCH_LIMIT,
)
from src.normalize import merge_paper_records, normalize_arxiv, normalize_s2
from src.schema import PaperRecord
from src.sources.arxiv import fetch_arxiv_soft
from src.sources.semantic_scholar import fetch_semantic_scholar_soft

DEFAULT_CONFIG_PATH = DATA_DIR / "survey_config.json"
ARXIV_MAX_RESULTS = 100


@dataclass
class SurveyConfig:
    topic_overview: str = "retrieval augmented generation"
    timeline_from_year: int = 2020
    timeline_to_year: int = 2026
    fields_of_study: list[str] = field(default_factory=lambda: ["Computer Science"])
    min_relevance_score: float = 0.35
    max_candidates_per_run: int = MAX_CANDIDATES_PER_RUN
    sources: list[str] = field(default_factory=lambda: ["semantic_scholar", "arxiv"])
    rank_method: str = "sbert"

    @classmethod
    def load(cls, path: Path | None = None) -> SurveyConfig:
        config_path = path or DEFAULT_CONFIG_PATH
        if not config_path.exists():
            return cls()
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return cls(
            topic_overview=data.get("topic_overview", cls.topic_overview),
            timeline_from_year=int(data.get("timeline_from_year", 2020)),
            timeline_to_year=int(data.get("timeline_to_year", 2026)),
            fields_of_study=list(data.get("fields_of_study") or ["Computer Science"]),
            min_relevance_score=float(data.get("min_relevance_score", 0.35)),
            max_candidates_per_run=int(
                data.get("max_candidates_per_run", MAX_CANDIDATES_PER_RUN)
            ),
            sources=list(data.get("sources") or ["semantic_scholar", "arxiv"]),
            rank_method=data.get("rank_method", "sbert"),
        )

    @property
    def year_filter(self) -> str:
        return f"{self.timeline_from_year}-{self.timeline_to_year}"

    @property
    def fields_of_study_param(self) -> str | None:
        if not self.fields_of_study:
            return None
        return ",".join(self.fields_of_study)


@dataclass
class FetchStats:
    api_calls: int = 0
    cache_hits: int = 0
    api_calls_by_source: dict[str, int] = field(default_factory=dict)
    papers_fetched_by_source: dict[str, int] = field(default_factory=dict)
    fetch_errors: list[dict[str, Any]] = field(default_factory=list)


def fetch_all_sources(
    query: str,
    config: SurveyConfig | None = None,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> tuple[list[PaperRecord], FetchStats]:
    """
    Fetch from configured sources, normalize, and merge by paper_id.

    Returns deduped PaperRecords and fetch statistics.
    """
    cfg = config or SurveyConfig.load()
    per_source_limit = limit or SEMANTIC_SCHOLAR_FETCH_LIMIT
    stats = FetchStats()
    records: list[PaperRecord] = []

    if "semantic_scholar" in cfg.sources:
        papers, error, cache_hit = fetch_semantic_scholar_soft(
            query,
            limit=per_source_limit,
            offset=offset,
            year=cfg.year_filter,
            fields_of_study=cfg.fields_of_study_param,
        )
        if cache_hit:
            stats.cache_hits += 1
        else:
            stats.api_calls += 1
            stats.api_calls_by_source["semantic_scholar"] = (
                stats.api_calls_by_source.get("semantic_scholar", 0) + 1
            )
        if error:
            stats.fetch_errors.append(
                {
                    "source": "semantic_scholar",
                    "query": query,
                    "offset": offset,
                    "error": error,
                }
            )
        s2_count = 0
        for raw in papers:
            record = normalize_s2(raw, source_query=query)
            if record:
                records.append(record)
                s2_count += 1
        if s2_count:
            stats.papers_fetched_by_source["semantic_scholar"] = (
                stats.papers_fetched_by_source.get("semantic_scholar", 0) + s2_count
            )

    if "arxiv" in cfg.sources:
        papers, error, cache_hit = fetch_arxiv_soft(
            query,
            start=offset,
            max_results=min(per_source_limit, ARXIV_MAX_RESULTS),
        )
        if cache_hit:
            stats.cache_hits += 1
        else:
            stats.api_calls += 1
            stats.api_calls_by_source["arxiv"] = (
                stats.api_calls_by_source.get("arxiv", 0) + 1
            )
        if error:
            stats.fetch_errors.append(
                {
                    "source": "arxiv",
                    "query": query,
                    "offset": offset,
                    "error": error,
                }
            )
        arxiv_count = 0
        for raw in papers:
            record = normalize_arxiv(raw, source_query=query)
            if record:
                records.append(record)
                arxiv_count += 1
        if arxiv_count:
            stats.papers_fetched_by_source["arxiv"] = (
                stats.papers_fetched_by_source.get("arxiv", 0) + arxiv_count
            )

    merged = merge_paper_records(records)
    if len(merged) > cfg.max_candidates_per_run:
        merged = merged[: cfg.max_candidates_per_run]
    return merged, stats


def records_to_agent_dicts(records: list[PaperRecord]) -> list[dict[str, Any]]:
    return [record.to_agent_dict() for record in records]
