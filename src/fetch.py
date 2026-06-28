"""
Multi-source fetch orchestration and survey configuration.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from src.config import (
    ARXIV_MAX_RESULTS,
    DEAD_QUERY_THRESHOLD,
    DEFAULT_CACHE_TTL_DAYS,
    DEFAULT_CONFIG_PATH,
    DEFAULT_DUAL_GATE_SCREENING,
    DEFAULT_FTS_PREFETCH_LIMIT,
    DISPLAY_LIMIT,
    DUAL_GATE_DELTA_MIN,
    DUAL_GATE_LEXICAL_MAX,
    DUAL_GATE_SBERT_MIN,
    MAX_PAGES_PER_QUERY,
    OPENALEX_MAX_PER_PAGE,
    RATE_LIMIT_THRESHOLD,
    SEMANTIC_SCHOLAR_FETCH_LIMIT,
    SEMANTIC_SCHOLAR_MAX_OFFSET,
)
from src.normalize import merge_paper_records, normalize_arxiv, normalize_openalex, normalize_s2
from src.rate_throttle import FetchThrottle, is_rate_limit_error
from src.schema import PaperRecord
from src.sources.arxiv import fetch_arxiv_soft
from src.sources.openalex import fetch_openalex_soft
from src.sources.semantic_scholar import fetch_semantic_scholar_soft

FIELDS_OF_STUDY_OPTIONS = [
    "",
    "Computer Science",
    "Medicine",
    "Biology",
    "Physics",
    "Chemistry",
    "Mathematics",
    "Engineering",
    "Environmental Science",
    "Psychology",
    "Economics",
]

RANK_METHOD_OPTIONS = ("sbert", "tfidf", "recency")
SOURCE_OPTIONS = ("semantic_scholar", "arxiv", "openalex")


@dataclass
class SurveyConfig:
    topic_overview: str = "retrieval augmented generation"
    research_questions: list[str] = field(default_factory=list)
    query_hints: list[str] = field(default_factory=list)
    timeline_from_year: int = 2020
    timeline_to_year: int = 2026
    fields_of_study: list[str] = field(default_factory=list)
    year_chunk_fetch: bool = True
    expand_acronyms: bool = False
    strict_timeline_filter: bool = False
    min_relevance_score: float = 0.25
    display_limit: int = DISPLAY_LIMIT
    max_queries: int = 12
    cache_ttl_days: float = DEFAULT_CACHE_TTL_DAYS
    dead_query_threshold: int = DEAD_QUERY_THRESHOLD
    rate_limit_threshold: int = RATE_LIMIT_THRESHOLD
    fts_prefetch_enabled: bool = False
    fts_prefetch_limit: int = DEFAULT_FTS_PREFETCH_LIMIT
    fuzzy_dedupe_enabled: bool = True
    dual_gate_screening: bool = DEFAULT_DUAL_GATE_SCREENING
    dual_gate_sbert_min: float = DUAL_GATE_SBERT_MIN
    dual_gate_lexical_max: float = DUAL_GATE_LEXICAL_MAX
    dual_gate_delta_min: float = DUAL_GATE_DELTA_MIN
    sources: list[str] = field(default_factory=lambda: ["semantic_scholar", "arxiv", "openalex"])
    rank_method: str = "sbert"

    @classmethod
    def load(cls, path: Path | None = None) -> SurveyConfig:
        config_path = path or DEFAULT_CONFIG_PATH
        if not config_path.exists():
            return cls()
        data = json.loads(config_path.read_text(encoding="utf-8"))
        fos = data.get("fields_of_study")
        return cls(
            topic_overview=data.get("topic_overview", cls.topic_overview),
            research_questions=list(data.get("research_questions") or []),
            query_hints=list(data.get("query_hints") or []),
            timeline_from_year=int(data.get("timeline_from_year", 2020)),
            timeline_to_year=int(data.get("timeline_to_year", 2026)),
            fields_of_study=list(fos) if fos else [],
            year_chunk_fetch=bool(data.get("year_chunk_fetch", True)),
            expand_acronyms=bool(data.get("expand_acronyms", False)),
            strict_timeline_filter=bool(data.get("strict_timeline_filter", False)),
            min_relevance_score=float(data.get("min_relevance_score", 0.25)),
            display_limit=int(data.get("display_limit", DISPLAY_LIMIT)),
            max_queries=int(data.get("max_queries", 12)),
            cache_ttl_days=float(data.get("cache_ttl_days", DEFAULT_CACHE_TTL_DAYS)),
            dead_query_threshold=int(data.get("dead_query_threshold", DEAD_QUERY_THRESHOLD)),
            rate_limit_threshold=int(data.get("rate_limit_threshold", RATE_LIMIT_THRESHOLD)),
            fts_prefetch_enabled=bool(data.get("fts_prefetch_enabled", False)),
            fts_prefetch_limit=int(data.get("fts_prefetch_limit", DEFAULT_FTS_PREFETCH_LIMIT)),
            fuzzy_dedupe_enabled=bool(data.get("fuzzy_dedupe_enabled", True)),
            dual_gate_screening=bool(data.get("dual_gate_screening", DEFAULT_DUAL_GATE_SCREENING)),
            dual_gate_sbert_min=float(data.get("dual_gate_sbert_min", DUAL_GATE_SBERT_MIN)),
            dual_gate_lexical_max=float(data.get("dual_gate_lexical_max", DUAL_GATE_LEXICAL_MAX)),
            dual_gate_delta_min=float(data.get("dual_gate_delta_min", DUAL_GATE_DELTA_MIN)),
            sources=list(data.get("sources") or ["semantic_scholar", "arxiv", "openalex"]),
            rank_method=data.get("rank_method", "sbert"),
        )

    def apply_overrides(self, overrides: dict[str, Any] | None) -> SurveyConfig:
        if not overrides:
            return self
        allowed = {f.name for f in fields(self)}
        updates: dict[str, Any] = {}
        for key, value in overrides.items():
            if key not in allowed or value is None:
                continue
            if key == "fields_of_study":
                if isinstance(value, str):
                    updates[key] = [value] if value.strip() else []
                elif isinstance(value, list):
                    updates[key] = [v for v in value if v]
            elif key == "sources":
                updates[key] = list(value) if isinstance(value, list) else self.sources
            elif key == "research_questions" or key == "query_hints":
                updates[key] = list(value) if isinstance(value, list) else self.__dict__[key]
            else:
                updates[key] = value
        return replace(self, **updates)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "topic_overview": self.topic_overview,
            "research_questions": list(self.research_questions),
            "query_hints": list(self.query_hints),
            "timeline_from_year": self.timeline_from_year,
            "timeline_to_year": self.timeline_to_year,
            "fields_of_study": list(self.fields_of_study),
            "year_chunk_fetch": self.year_chunk_fetch,
            "expand_acronyms": self.expand_acronyms,
            "strict_timeline_filter": self.strict_timeline_filter,
            "min_relevance_score": self.min_relevance_score,
            "display_limit": self.display_limit,
            "max_queries": self.max_queries,
            "cache_ttl_days": self.cache_ttl_days,
            "dead_query_threshold": self.dead_query_threshold,
            "rate_limit_threshold": self.rate_limit_threshold,
            "fts_prefetch_enabled": self.fts_prefetch_enabled,
            "fts_prefetch_limit": self.fts_prefetch_limit,
            "fuzzy_dedupe_enabled": self.fuzzy_dedupe_enabled,
            "dual_gate_screening": self.dual_gate_screening,
            "dual_gate_sbert_min": self.dual_gate_sbert_min,
            "dual_gate_lexical_max": self.dual_gate_lexical_max,
            "dual_gate_delta_min": self.dual_gate_delta_min,
            "sources": list(self.sources),
            "rank_method": self.rank_method,
            "options": {
                "fields_of_study": FIELDS_OF_STUDY_OPTIONS,
                "rank_method": list(RANK_METHOD_OPTIONS),
                "sources": list(SOURCE_OPTIONS),
            },
        }

    @property
    def fields_of_study_param(self) -> str | None:
        if not self.fields_of_study:
            return None
        return ",".join(self.fields_of_study)

    def year_chunks(self) -> list[str]:
        if not self.year_chunk_fetch:
            return [f"{self.timeline_from_year}-{self.timeline_to_year}"]
        if self.timeline_from_year >= self.timeline_to_year:
            return [str(self.timeline_from_year)]
        return [str(y) for y in range(self.timeline_from_year, self.timeline_to_year + 1)]


@dataclass
class FetchStats:
    api_calls: int = 0
    cache_hits: int = 0
    rate_limit_errors: int = 0
    api_calls_by_source: dict[str, int] = field(default_factory=dict)
    papers_fetched_by_source: dict[str, int] = field(default_factory=dict)
    fetch_errors: list[dict[str, Any]] = field(default_factory=list)


def _fetch_s2_page(
    query: str,
    *,
    year: str | None,
    offset: int,
    limit: int,
    fields_of_study: str | None,
    stats: FetchStats,
) -> list[PaperRecord]:
    papers, error, cache_hit = fetch_semantic_scholar_soft(
        query, limit=limit, offset=offset, year=year, fields_of_study=fields_of_study
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
                "year": year,
                "offset": offset,
                "error": error,
            }
        )
        if is_rate_limit_error(error):
            stats.rate_limit_errors += 1
    records: list[PaperRecord] = []
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
    return records


def _fetch_arxiv_page(
    query: str,
    *,
    start: int,
    limit: int,
    stats: FetchStats,
) -> list[PaperRecord]:
    papers, error, cache_hit = fetch_arxiv_soft(query, start=start, max_results=limit)
    if cache_hit:
        stats.cache_hits += 1
    else:
        stats.api_calls += 1
        stats.api_calls_by_source["arxiv"] = stats.api_calls_by_source.get("arxiv", 0) + 1
    if error:
        stats.fetch_errors.append(
            {"source": "arxiv", "query": query, "offset": start, "error": error}
        )
        if is_rate_limit_error(error):
            stats.rate_limit_errors += 1
    records: list[PaperRecord] = []
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
    return records


def _fetch_openalex_pages(
    query: str,
    *,
    year: str | None,
    stats: FetchStats,
) -> list[PaperRecord]:
    publication_year: int | None = None
    if year and year.isdigit():
        publication_year = int(year)
    elif year and "-" not in year:
        publication_year = int(year) if year.isdigit() else None

    records: list[PaperRecord] = []
    oa_count = 0
    cursor: str | None = None

    for _ in range(MAX_PAGES_PER_QUERY):
        papers, error, cache_hit, next_cursor = fetch_openalex_soft(
            query,
            per_page=OPENALEX_MAX_PER_PAGE,
            cursor=cursor,
            publication_year=publication_year,
        )
        if cache_hit:
            stats.cache_hits += 1
        else:
            stats.api_calls += 1
            stats.api_calls_by_source["openalex"] = (
                stats.api_calls_by_source.get("openalex", 0) + 1
            )
        if error:
            stats.fetch_errors.append(
                {
                    "source": "openalex",
                    "query": query,
                    "year": year,
                    "cursor": cursor,
                    "error": error,
                }
            )
            if is_rate_limit_error(error):
                stats.rate_limit_errors += 1
            break

        for raw in papers:
            record = normalize_openalex(raw, source_query=query)
            if record:
                records.append(record)
                oa_count += 1

        if not next_cursor or len(papers) < OPENALEX_MAX_PER_PAGE:
            break
        cursor = next_cursor

    if oa_count:
        stats.papers_fetched_by_source["openalex"] = (
            stats.papers_fetched_by_source.get("openalex", 0) + oa_count
        )
    return records


def _merge_fetch_stats(into: FetchStats, other: FetchStats) -> None:
    into.api_calls += other.api_calls
    into.cache_hits += other.cache_hits
    into.rate_limit_errors += other.rate_limit_errors
    into.fetch_errors.extend(other.fetch_errors)
    for source, count in other.api_calls_by_source.items():
        into.api_calls_by_source[source] = into.api_calls_by_source.get(source, 0) + count
    for source, count in other.papers_fetched_by_source.items():
        into.papers_fetched_by_source[source] = (
            into.papers_fetched_by_source.get(source, 0) + count
        )


def _fetch_semantic_scholar_source(
    query: str,
    cfg: SurveyConfig,
    *,
    offset: int,
    limit: int,
) -> tuple[list[PaperRecord], FetchStats]:
    stats = FetchStats()
    records: list[PaperRecord] = []
    for year in cfg.year_chunks():
        page_offset = offset
        for _ in range(MAX_PAGES_PER_QUERY):
            if page_offset > SEMANTIC_SCHOLAR_MAX_OFFSET:
                break
            page = _fetch_s2_page(
                query,
                year=year,
                offset=page_offset,
                limit=limit,
                fields_of_study=cfg.fields_of_study_param,
                stats=stats,
            )
            records.extend(page)
            if len(page) < limit:
                break
            page_offset += limit
    return records, stats


def _fetch_arxiv_source(
    query: str,
    cfg: SurveyConfig,
    *,
    offset: int,
    limit: int,
) -> tuple[list[PaperRecord], FetchStats]:
    stats = FetchStats()
    records: list[PaperRecord] = []
    page_start = offset
    page_size = min(limit, ARXIV_MAX_RESULTS)
    for _ in range(MAX_PAGES_PER_QUERY):
        page = _fetch_arxiv_page(query, start=page_start, limit=page_size, stats=stats)
        records.extend(page)
        if len(page) < page_size:
            break
        page_start += page_size
    return records, stats


def _fetch_openalex_source(query: str, cfg: SurveyConfig) -> tuple[list[PaperRecord], FetchStats]:
    stats = FetchStats()
    records: list[PaperRecord] = []
    for year in cfg.year_chunks():
        year_label = year if cfg.year_chunk_fetch else None
        records.extend(_fetch_openalex_pages(query, year=year_label, stats=stats))
    return records, stats


def fetch_all_sources(
    query: str,
    config: SurveyConfig | None = None,
    *,
    offset: int = 0,
    limit: int | None = None,
    throttle: FetchThrottle | None = None,
) -> tuple[list[PaperRecord], FetchStats]:
    """Fetch from configured sources in parallel with year-chunking and pagination."""
    cfg = config or SurveyConfig.load()
    per_page = limit or SEMANTIC_SCHOLAR_FETCH_LIMIT
    merged_stats = FetchStats()
    all_records: list[PaperRecord] = []
    fetch_throttle = throttle or FetchThrottle()
    max_workers = fetch_throttle.effective_workers(len(cfg.sources))
    futures = []

    with ThreadPoolExecutor(max_workers=max(max_workers, 1)) as pool:
        if "semantic_scholar" in cfg.sources:
            futures.append(
                pool.submit(
                    _fetch_semantic_scholar_source,
                    query,
                    cfg,
                    offset=offset,
                    limit=per_page,
                )
            )
        if "arxiv" in cfg.sources:
            futures.append(
                pool.submit(_fetch_arxiv_source, query, cfg, offset=offset, limit=per_page)
            )
        if "openalex" in cfg.sources:
            futures.append(pool.submit(_fetch_openalex_source, query, cfg))

        for future in as_completed(futures):
            records, stats = future.result()
            all_records.extend(records)
            _merge_fetch_stats(merged_stats, stats)

    fetch_throttle.observe_errors(
        merged_stats.fetch_errors,
        threshold=cfg.rate_limit_threshold,
    )

    return merge_paper_records(all_records), merged_stats


def records_to_paper_dicts(records: list[PaperRecord]) -> list[dict[str, Any]]:
    return [record.to_paper_dict() for record in records]


records_to_agent_dicts = records_to_paper_dicts
