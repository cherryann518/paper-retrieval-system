"""
1st-baseline retrieval pipeline

Orchestrates: local corpus + live fetch → dedupe → rank → screen → full corpus + display slice.
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
from src.schema import dedupe_papers
from src.score_divergence import score_divergence_summary
from src.screening import apply_screening
from src.store import load_local_corpus_for_query, record_screening_batch, upsert_papers_batch


def _resolve_search_query(query: str, config: SurveyConfig) -> str:
    stripped = query.strip()
    if not config.expand_acronyms or " " in stripped:
        return stripped
    return ML_ACRONYM_EXPANSIONS.get(stripped.lower(), stripped)


def run_retrieval(
    query: str,
    *,
    survey_config: SurveyConfig | None = None,
    config_overrides: dict[str, Any] | None = None,
    rank_method: RankMethod | None = None,
    survey_mode: bool = False,
    use_local_corpus: bool = True,
) -> dict[str, Any]:
    """
    Run retrieval for one or more canonical queries.

    Returns:
      papers          — full accepted ranked corpus (for RAG downstream)
      papers_display  — top display_limit preview (CLI / web cards)
      rejects         — screened-out papers with reasons (also persisted to DB)
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
    store_stats = {"inserted": 0, "updated": 0, "source_hits": 0, "merged_by_identifier": 0}
    aggregate_stats_api = 0
    aggregate_stats_cache = 0
    papers_fetched_by_source: dict[str, int] = {}

    local_papers: list[dict] = []
    live_papers: list[dict] = []

    for search_query in search_queries:
        resolved = _resolve_search_query(search_query, config)

        if use_local_corpus:
            local_papers.extend(load_local_corpus_for_query(resolved))

        live_records, stats = fetch_all_sources(resolved, config)
        aggregate_stats_api += stats.api_calls
        aggregate_stats_cache += stats.cache_hits
        fetch_errors.extend(stats.fetch_errors)
        for source, count in stats.papers_fetched_by_source.items():
            papers_fetched_by_source[source] = papers_fetched_by_source.get(source, 0) + count

        if live_records:
            batch_store = upsert_papers_batch(live_records)
            for key in store_stats:
                store_stats[key] += batch_store.get(key, 0)
            live_papers.extend(records_to_paper_dicts(live_records))

    pool = dedupe_papers(local_papers + live_papers)
    rank_query = _resolve_search_query(original_query, config)

    ranked = rank_papers(
        rank_query,
        pool,
        methods=["sbert", "tfidf", "recency"],
        primary_method=primary_rank,
        from_year=config.timeline_from_year,
        to_year=config.timeline_to_year,
        include_lexical=True,
    )

    accepted, rejects = apply_screening(ranked, config)
    record_screening_batch(original_query, accepted, rejects)
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
    divergence = score_divergence_summary(accepted)

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
        "papers_from_local": len(local_papers),
        "papers_in_pool": len(pool),
        "papers_accepted": len(accepted),
        "papers_rejected": len(rejects),
        "papers_display": len(papers_display),
        "display_limit": display_limit,
        "fetch_error_count": len(fetch_errors),
        "rank_method": primary_rank,
        "embedding_model": EMBEDDING_MODEL_NAME,
        "embedding_package_version": embedding_package_version(),
        "lexical_scorer": LEXICAL_VERSION,
        "min_relevance_score": config.min_relevance_score,
        "store_inserted": store_stats["inserted"],
        "store_updated": store_stats["updated"],
        "store_merged_by_identifier": store_stats["merged_by_identifier"],
        "top_score": round(scores[0], 4) if scores else 0.0,
        "papers_fetched_by_source": papers_fetched_by_source,
        "search_queries_run": len(search_queries),
        "search_queries_skipped": len(skipped_queries),
        "parallel_fetch": True,
        "query_state": query_state,
        "score_divergence": divergence,
    }

    return {
        "query": original_query,
        "search_queries": search_queries,
        "search_queries_all": all_search_queries,
        "skipped_queries": skipped_queries,
        "search_query": search_queries[0],
        "config": config.to_public_dict(),
        "papers": accepted,
        "papers_display": papers_display,
        "rejects": rejects,
        "status": status,
        "metrics": metrics,
        "fetch_errors": fetch_errors,
        "survey_mode": survey_mode,
    }
