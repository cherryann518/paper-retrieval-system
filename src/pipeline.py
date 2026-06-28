"""
1st-baseline retrieval pipeline

Orchestrates: local corpus + FTS prefetch + live fetch → dedupe → rank → screen → full corpus + display slice.
"""

from __future__ import annotations

import time
from typing import Any

from src.config import EMBEDDING_MODEL_NAME, ML_ACRONYM_EXPANSIONS, embedding_package_version
from src.fetch import SurveyConfig, fetch_all_sources, records_to_paper_dicts
from src.lexical import LEXICAL_VERSION
from src.loop_control import filter_dead_queries, get_query_state, record_query_outcome
from src.query_builder import build_canonical_queries
from src.rank import RankMethod, rank_papers
from src.rate_throttle import FetchThrottle
from src.schema import dedupe_papers
from src.score_divergence import score_divergence_summary
from src.screening import apply_screening
from src.store import (
    count_possible_duplicates,
    load_local_corpus_for_query,
    record_screening_batch,
    search_corpus_fts,
    upsert_papers_batch,
)


def _resolve_search_query(query: str, config: SurveyConfig) -> str:
    stripped = query.strip()
    if not config.expand_acronyms or " " in stripped:
        return stripped
    return ML_ACRONYM_EXPANSIONS.get(stripped.lower(), stripped)


def _accepted_from_query(accepted: list[dict], search_query: str) -> int:
    resolved = search_query.strip()
    count = 0
    for paper in accepted:
        queries = paper.get("source_queries") or []
        if resolved in queries or any(resolved == q.strip() for q in queries):
            count += 1
    return count


def run_retrieval(
    query: str,
    *,
    survey_config: SurveyConfig | None = None,
    config_overrides: dict[str, Any] | None = None,
    rank_method: RankMethod | None = None,
    survey_mode: bool = False,
    use_local_corpus: bool = True,
    skip_screening: bool = False,
) -> dict[str, Any]:
    """
    Run retrieval for one or more canonical queries.

    Returns:
      ranked_pool     — full ranked list before screening (retrieval eval)
      papers          — accepted ranked corpus (or ranked_pool if skip_screening)
      papers_display  — top display_limit preview (CLI / web cards)
      rejects         — screened-out papers with reasons (empty if skip_screening)
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")

    original_query = query.strip()
    base_config = survey_config or SurveyConfig.load()
    config = base_config.apply_overrides(config_overrides)
    primary_rank: RankMethod = rank_method or config.rank_method  # type: ignore[assignment]

    from src.cache import set_cache_ttl_days

    set_cache_ttl_days(config.cache_ttl_days)

    all_search_queries = build_canonical_queries(
        config,
        user_query=original_query,
        include_config_queries=survey_mode,
    )
    if not all_search_queries:
        raise ValueError("no search queries generated")

    search_queries, skipped_queries = filter_dead_queries(
        all_search_queries,
        threshold=config.dead_query_threshold,
        survey_mode=survey_mode,
    )

    started = time.perf_counter()
    fetch_errors: list[dict] = []
    store_stats = {
        "inserted": 0,
        "updated": 0,
        "source_hits": 0,
        "merged_by_identifier": 0,
        "possible_duplicates_flagged": 0,
    }
    aggregate_stats_api = 0
    aggregate_stats_cache = 0
    papers_fetched_by_source: dict[str, int] = {}
    throttle = FetchThrottle()

    local_papers: list[dict] = []
    fts_prefetch_papers: list[dict] = []
    live_papers: list[dict] = []

    if use_local_corpus:
        for search_query in search_queries:
            resolved = _resolve_search_query(search_query, config)
            local_papers.extend(load_local_corpus_for_query(resolved))

        if config.fts_prefetch_enabled:
            fts_query = _resolve_search_query(original_query, config)
            fts_prefetch_papers = search_corpus_fts(
                fts_query,
                limit=config.fts_prefetch_limit,
            )
            local_papers.extend(fts_prefetch_papers)

    for search_query in search_queries:
        resolved = _resolve_search_query(search_query, config)

        live_records, stats = fetch_all_sources(resolved, config, throttle=throttle)
        aggregate_stats_api += stats.api_calls
        aggregate_stats_cache += stats.cache_hits
        fetch_errors.extend(stats.fetch_errors)
        for source, count in stats.papers_fetched_by_source.items():
            papers_fetched_by_source[source] = papers_fetched_by_source.get(source, 0) + count

        if live_records:
            batch_store = upsert_papers_batch(
                live_records,
                fuzzy_dedupe_enabled=config.fuzzy_dedupe_enabled,
            )
            for key in store_stats:
                store_stats[key] += batch_store.get(key, 0)
            live_papers.extend(records_to_paper_dicts(live_records))

    pool = dedupe_papers(local_papers + live_papers)
    rank_query = _resolve_search_query(original_query, config)

    ranked_pool = rank_papers(
        rank_query,
        pool,
        methods=["sbert", "tfidf", "recency"],
        primary_method=primary_rank,
        from_year=config.timeline_from_year,
        to_year=config.timeline_to_year,
        include_lexical=True,
        include_sbert_fields=True,
    )

    if skip_screening:
        accepted = ranked_pool
        rejects: list[dict] = []
    else:
        accepted, rejects = apply_screening(ranked_pool, config)
        record_screening_batch(original_query, accepted, rejects)

    # G2 — record per canonical sub-query for dead-query skip (H1)
    for search_query in search_queries:
        resolved = _resolve_search_query(search_query, config)
        sub_accepted = _accepted_from_query(accepted, resolved)
        record_query_outcome(
            resolved,
            accepted_count=sub_accepted,
            rejected_count=max(0, len(rejects)),
            error_count=len(fetch_errors),
        )

    record_query_outcome(
        original_query,
        accepted_count=len(accepted),
        rejected_count=len(rejects),
        error_count=len(fetch_errors),
    )

    display_limit = max(config.display_limit, 0)
    papers_display = accepted[:display_limit] if display_limit else []

    latency_ms = (time.perf_counter() - started) * 1000
    scores = [p["relevance_score"] for p in accepted]
    query_state = get_query_state(original_query)
    divergence_accepted = score_divergence_summary(accepted)
    divergence_pool = score_divergence_summary(ranked_pool)
    possible_duplicate_total = count_possible_duplicates()

    if not accepted and fetch_errors:
        status = "failure"
    elif fetch_errors:
        status = "partial_success"
    else:
        status = "ok"

    metrics = {
        "latency_ms": round(latency_ms, 1),
        "api_calls": aggregate_stats_api,
        "cache_hits": aggregate_stats_cache,
        "papers_fetched_live": len(live_papers),
        "papers_from_local": len(local_papers) - len(fts_prefetch_papers),
        "papers_from_fts_prefetch": len(fts_prefetch_papers),
        "fts_prefetch_enabled": config.fts_prefetch_enabled,
        "papers_in_pool": len(pool),
        "papers_ranked": len(ranked_pool),
        "papers_accepted": len(accepted),
        "papers_rejected": len(rejects),
        "papers_display": len(papers_display),
        "display_limit": display_limit,
        "skip_screening": skip_screening,
        "dual_gate_screening": config.dual_gate_screening,
        "fetch_error_count": len(fetch_errors),
        "rate_limit_errors": throttle.rate_limit_events,
        "fetch_throttled": throttle.throttled,
        "fetch_max_workers_final": throttle.effective_workers(len(config.sources)),
        "rank_method": primary_rank,
        "embedding_model": EMBEDDING_MODEL_NAME,
        "embedding_package_version": embedding_package_version(),
        "lexical_scorer": LEXICAL_VERSION,
        "min_relevance_score": config.min_relevance_score,
        "store_inserted": store_stats["inserted"],
        "store_updated": store_stats["updated"],
        "store_merged_by_identifier": store_stats["merged_by_identifier"],
        "possible_duplicates_flagged": store_stats["possible_duplicates_flagged"],
        "possible_duplicates_total": possible_duplicate_total,
        "top_score": round(scores[0], 4) if scores else 0.0,
        "papers_fetched_by_source": papers_fetched_by_source,
        "search_queries_run": len(search_queries),
        "search_queries_skipped": len(skipped_queries),
        "parallel_fetch": True,
        "query_state": query_state,
        "score_divergence": divergence_accepted,
        "score_divergence_pool": divergence_pool,
    }

    return {
        "query": original_query,
        "search_queries": search_queries,
        "search_queries_all": all_search_queries,
        "skipped_queries": skipped_queries,
        "search_query": search_queries[0],
        "config": config.to_public_dict(),
        "ranked_pool": ranked_pool,
        "papers": accepted,
        "papers_display": papers_display,
        "rejects": rejects,
        "status": status,
        "metrics": metrics,
        "fetch_errors": fetch_errors,
        "survey_mode": survey_mode,
    }
