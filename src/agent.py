"""
Agentic search loop: retrieve, score, optionally refine query via Ollama.

Supports per-round metrics, fail-soft fetching with pagination, and eval modes.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Literal

from src.config import (
    MAX_PAGES_PER_QUERY,
    MAX_REFINEMENT_ROUNDS,
    MAX_RESULTS_RETURN,
    MIN_GOOD_PAPERS,
    MIN_SCORE_GAP,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    SCORE_GOOD,
    SCORE_TOP_MIN,
    SEMANTIC_SCHOLAR_FETCH_LIMIT,
)
from src.fetch import SurveyConfig, fetch_all_sources, records_to_agent_dicts
from src.rank import RankMethod, rank_papers
from src.schema import agent_paper_key
from src.store import upsert_papers_batch

SearchMode = Literal["agent", "single_fetch", "multi_fetch_same"]

OLLAMA_SYSTEM_PROMPT = """You help refine academic paper search queries for Semantic Scholar.

Rules:
- Output ONLY a single search query string on one line.
- No quotes, no explanation, no JSON, no bullet points.
- Stay in the SAME research field as the original user topic and the retrieved paper titles.
- Prefer 3-8 words, under 100 characters. Use standard academic terms from CS/ML/NLP when the topic is about AI.
- Do not invent paper titles or author names.
- If the user topic is an ambiguous acronym (e.g. RAG), infer the field from retrieved titles and the original topic — do NOT switch to unrelated domains (e.g. biology/medical RAG genes when papers are about language models)."""

ML_ACRONYM_EXPANSIONS: dict[str, str] = {
    "rag": "retrieval augmented generation",
    "llm": "large language models",
    "llms": "large language models",
    "cot": "chain of thought reasoning language models",
    "rlhf": "reinforcement learning from human feedback",
}

REFINEMENT_MAX_CHARS = 120

REFINEMENT_HINTS: dict[str, str] = {
    "no_papers": (
        "The search returned nothing. Broaden the query using standard academic "
        "terms and well-known subfield vocabulary."
    ),
    "top_score_low": (
        "Results look off-topic or too generic. Rephrase using precise technical "
        "terms researchers use in paper titles (methods, models, tasks)."
    ),
    "too_few_good_papers": (
        "Some related papers appeared but not enough strong matches. Try synonyms, "
        "abbreviations, or a closely related subtopic while staying on theme."
    ),
    "flat_scores": (
        "Results are ambiguous — many weak matches, no clear winner. Narrow the "
        "query to a specific method, application, or problem setting."
    ),
}


class OllamaError(Exception):
    """Raised when the local Ollama API is unavailable or returns an error."""


def dedupe_papers(papers: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for paper in papers:
        key = agent_paper_key(paper)
        if key in seen:
            continue
        seen.add(key)
        unique.append(paper)
    return unique


def results_acceptable(ranked: list[dict]) -> tuple[bool, str]:
    if not ranked:
        return False, "no_papers"

    scores = [paper["relevance_score"] for paper in ranked]
    top = scores[0]
    good_count = sum(1 for score in scores if score >= SCORE_GOOD)

    if top < SCORE_TOP_MIN:
        return False, f"top_score_low ({top:.3f} < {SCORE_TOP_MIN})"

    if good_count < MIN_GOOD_PAPERS:
        return False, f"too_few_good_papers ({good_count} < {MIN_GOOD_PAPERS})"

    top_n = scores[: min(5, len(scores))]
    median_top = sorted(top_n)[len(top_n) // 2]
    if top - median_top < MIN_SCORE_GAP:
        return False, f"flat_scores (top={top:.3f}, median_top5={median_top:.3f})"

    return True, "ok"


def _score_summary(ranked: list[dict], top_k: int = 10) -> dict:
    if not ranked:
        return {
            "top_score": 0.0,
            "mean_top5": 0.0,
            "good_count": 0,
            "top10_good_count": 0,
        }
    scores = [paper["relevance_score"] for paper in ranked]
    top_n = scores[: min(5, len(scores))]
    top_k_scores = scores[: min(top_k, len(scores))]
    return {
        "top_score": round(scores[0], 4),
        "mean_top5": round(sum(top_n) / len(top_n), 4),
        "good_count": sum(1 for score in scores if score >= SCORE_GOOD),
        "top10_good_count": sum(1 for score in top_k_scores if score >= SCORE_GOOD),
    }


def _reason_key(reason: str) -> str:
    return reason.split()[0] if reason else "no_papers"


def _format_results_for_prompt(ranked: list[dict], limit: int = 5) -> str:
    lines = []
    for index, paper in enumerate(ranked[:limit], start=1):
        title = paper.get("title") or "Untitled"
        score = paper.get("relevance_score", 0)
        abstract = (paper.get("abstract") or "").strip()
        snippet = abstract[:120] + "..." if len(abstract) > 120 else abstract
        snippet_part = f" — {snippet}" if snippet else ""
        lines.append(f"{index}. {title} | {score:.3f}{snippet_part}")
    return "\n".join(lines) if lines else "(no results)"


def _effective_topic(query: str) -> str:
    stripped = query.strip()
    key = stripped.lower()
    if " " not in stripped and key in ML_ACRONYM_EXPANSIONS:
        return ML_ACRONYM_EXPANSIONS[key]
    return stripped


def _parse_refined_query(raw: str) -> str:
    query = raw.strip().split("\n")[0].strip().strip("\"'")
    if not query:
        raise ValueError("empty refined query")
    if len(query) > REFINEMENT_MAX_CHARS:
        trimmed = query[:REFINEMENT_MAX_CHARS]
        if " " in trimmed:
            trimmed = trimmed.rsplit(" ", 1)[0]
        query = trimmed.strip()
    if not query:
        raise ValueError("invalid refined query")
    return query


def _ollama_generate(system: str, prompt: str) -> str:
    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 40},
        }
    ).encode()
    request = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
            data = json.loads(response.read().decode())
    except urllib.error.URLError as exc:
        raise OllamaError(f"Ollama request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise OllamaError("Invalid JSON response from Ollama") from exc

    text = data.get("response", "").strip()
    if not text:
        raise OllamaError("Ollama returned an empty response")
    return text


def ollama_refine_query(
    original_query: str,
    search_query: str,
    ranked: list[dict],
    reason: str,
    refinement_round: int,
) -> str:
    hint = REFINEMENT_HINTS.get(_reason_key(reason), REFINEMENT_HINTS["top_score_low"])
    topic_note = ""
    expanded = _effective_topic(original_query)
    if expanded != original_query.strip():
        topic_note = (
            f"\nNote: '{original_query}' likely means '{expanded}' in CS/ML/NLP — "
            "use that field, not unrelated acronym expansions."
        )

    user_prompt = f"""Original user topic: {original_query}
Why results were rejected: {reason}
Strategy: {hint}{topic_note}
Previous search query: {search_query}
Refinement attempt: {refinement_round} of {MAX_REFINEMENT_ROUNDS}

Top retrieved papers (may be weak matches):
{_format_results_for_prompt(ranked)}

Write one improved Semantic Scholar search query (3-8 words, under 100 characters)."""

    strict_suffix = (
        "\n\nOutput ONLY the query string on one line. "
        "3-8 words. Under 100 characters. No explanation."
    )

    last_error: ValueError | None = None
    for attempt, prompt in enumerate((user_prompt, user_prompt + strict_suffix)):
        raw = _ollama_generate(OLLAMA_SYSTEM_PROMPT, prompt)
        try:
            return _parse_refined_query(raw)
        except ValueError as exc:
            last_error = exc
            print(f"[agent] invalid refined query (attempt {attempt + 1}): {raw!r}", flush=True)

    raise OllamaError(f"Could not parse a valid refined query: {last_error}")


def _fetch_query_pages(
    search_query: str,
    max_pages: int,
    counters: dict,
    fetch_errors: list[dict],
    config: SurveyConfig,
) -> tuple[list[dict], int, dict[str, int]]:
    """Fail-soft paginated multi-source fetch. Returns (papers, pages_fetched, store_stats)."""
    batch: list[dict] = []
    pages_fetched = 0
    store_stats = {"inserted": 0, "updated": 0, "source_hits": 0}
    for page in range(max_pages):
        offset = page * SEMANTIC_SCHOLAR_FETCH_LIMIT
        records, stats = fetch_all_sources(
            search_query,
            config,
            offset=offset,
            limit=SEMANTIC_SCHOLAR_FETCH_LIMIT,
        )
        counters["api_calls"] += stats.api_calls
        counters["cache_hits"] += stats.cache_hits
        for source, count in stats.api_calls_by_source.items():
            key = f"api_calls_{source}"
            counters[key] = counters.get(key, 0) + count
        fetch_errors.extend(stats.fetch_errors)
        pages_fetched += 1

        if stats.fetch_errors:
            for err in stats.fetch_errors:
                print(
                    f"[agent] fetch failed source={err.get('source')} "
                    f"query={search_query!r} page={page}: {err.get('error')}",
                    flush=True,
                )

        if records:
            page_store = upsert_papers_batch(records)
            for key in store_stats:
                store_stats[key] += page_store.get(key, 0)
            batch.extend(records_to_agent_dicts(records))

        if len(records) < SEMANTIC_SCHOLAR_FETCH_LIMIT:
            break
    return batch, pages_fetched, store_stats


def run_search_agent(
    original_query: str,
    *,
    mode: SearchMode = "agent",
    refine: bool = True,
    max_pages: int | None = None,
    include_ranked_pool: bool = False,
    survey_config: SurveyConfig | None = None,
    rank_method: RankMethod | None = None,
) -> dict:
    """
    Multi-source search, rank by relevance, optionally refine via Ollama.

    Modes:
      agent            — full loop with optional Ollama refinement (default)
      single_fetch     — one query, one round, no refinement
      multi_fetch_same — re-fetch the same query each round, no Ollama
    """
    if not original_query or not original_query.strip():
        raise ValueError("query must be a non-empty string")

    original_query = original_query.strip()
    rank_topic = _effective_topic(original_query)
    pages_per_query = max_pages if max_pages is not None else MAX_PAGES_PER_QUERY
    config = survey_config or SurveyConfig.load()
    primary_rank: RankMethod = rank_method or config.rank_method  # type: ignore[assignment]

    if mode == "single_fetch":
        max_rounds = 0
        refine = False
    elif mode == "multi_fetch_same":
        max_rounds = MAX_REFINEMENT_ROUNDS
        refine = False
    else:
        max_rounds = MAX_REFINEMENT_ROUNDS if refine else 0

    search_query = rank_topic if rank_topic != original_query else original_query
    all_papers: list[dict] = []
    search_queries_used: list[str] = []
    round_records: list[dict] = []
    fetch_errors: list[dict] = []
    refinement_errors: list[str] = []
    counters: dict = {
        "api_calls": 0,
        "cache_hits": 0,
        "ollama_calls": 0,
    }
    started = time.perf_counter()

    refinement_round = 0
    ranked: list[dict] = []
    reason = "no_papers"
    ollama_unavailable = False
    store_stats = {"inserted": 0, "updated": 0, "source_hits": 0}

    while refinement_round <= max_rounds:
        print(
            f"[agent] round={refinement_round} search_query={search_query!r}",
            flush=True,
        )
        round_fetch_errors: list[dict] = []
        batch, pages_fetched, page_store = _fetch_query_pages(
            search_query,
            pages_per_query,
            counters,
            round_fetch_errors,
            config,
        )
        for key in store_stats:
            store_stats[key] += page_store.get(key, 0)
        fetch_errors.extend(round_fetch_errors)
        search_queries_used.append(search_query)
        all_papers = dedupe_papers(all_papers + batch)
        ranked = rank_papers(
            rank_topic,
            all_papers,
            methods=["sbert", "tfidf", "recency"],
            primary_method=primary_rank,
            from_year=config.timeline_from_year,
            to_year=config.timeline_to_year,
        )

        ok, reason = results_acceptable(ranked)
        batch_ranked = (
            rank_papers(
                rank_topic,
                batch,
                methods=["sbert", "tfidf", "recency"],
                primary_method=primary_rank,
                from_year=config.timeline_from_year,
                to_year=config.timeline_to_year,
            )
            if batch
            else []
        )
        round_records.append(
            {
                "round": refinement_round,
                "search_query": search_query,
                "batch_size": len(batch),
                "pages_fetched": pages_fetched,
                "pool_size": len(all_papers),
                "acceptable": ok,
                "reason": reason,
                "fetch_errors": round_fetch_errors,
                "cache_hits": counters["cache_hits"],
                **_score_summary(ranked),
                "batch_top_score": _score_summary(batch_ranked)["top_score"],
            }
        )
        print(f"[agent] acceptable={ok} reason={reason}", flush=True)

        if ok:
            break

        if refinement_round >= max_rounds:
            break

        if mode == "multi_fetch_same":
            refinement_round += 1
            continue

        if not refine:
            break

        try:
            search_query = ollama_refine_query(
                original_query,
                search_query,
                ranked,
                reason,
                refinement_round + 1,
            )
            counters["ollama_calls"] += 1
            print(f"[agent] refined query={search_query!r}", flush=True)
        except OllamaError as exc:
            print(f"[agent] Ollama refinement failed: {exc}", flush=True)
            refinement_errors.append(str(exc))
            ollama_unavailable = True
            break

        refinement_round += 1

    latency_ms = (time.perf_counter() - started) * 1000
    ok, reason = results_acceptable(ranked)

    if not ranked and fetch_errors and not all_papers:
        status = "failure"
    elif fetch_errors or ollama_unavailable or refinement_errors:
        status = "partial_success" if ranked else "failure"
    elif ok:
        status = "ok"
    else:
        status = "weak_results"

    score_summary = _score_summary(ranked)
    metrics = {
        "latency_ms": round(latency_ms, 1),
        "api_calls": counters["api_calls"],
        "cache_hits": counters["cache_hits"],
        "api_calls_semantic_scholar": counters.get("api_calls_semantic_scholar", 0),
        "api_calls_arxiv": counters.get("api_calls_arxiv", 0),
        "ollama_calls": counters["ollama_calls"],
        "papers_fetched": len(all_papers),
        "papers_returned": min(len(ranked), MAX_RESULTS_RETURN),
        "fetch_error_count": len(fetch_errors),
        "rank_method": primary_rank,
        "store_inserted": store_stats["inserted"],
        "store_updated": store_stats["updated"],
        **score_summary,
    }

    if ranked:
        metrics["scores_by_method"] = {
            name: round(sum(p.get("scores", {}).get(name, 0) for p in ranked[:10]) / min(10, len(ranked)), 4)
            for name in ("sbert_cosine", "tfidf_cosine", "recency")
        }

    result = {
        "query": original_query,
        "mode": mode,
        "papers": ranked[:MAX_RESULTS_RETURN],
        "status": status,
        "refinement_rounds": refinement_round,
        "search_queries_used": search_queries_used,
        "acceptance_reason": reason,
        "rounds": round_records,
        "metrics": metrics,
        "fetch_errors": fetch_errors,
        "refinement_errors": refinement_errors,
        "rank_topic": rank_topic,
    }
    if include_ranked_pool:
        result["ranked_pool"] = [
            {
                "title": paper.get("title"),
                "authors": paper.get("authors"),
                "abstract": paper.get("abstract"),
                "relevance_score": paper.get("relevance_score"),
                "scores": paper.get("scores"),
                "year": paper.get("year"),
                "externalIds": paper.get("externalIds"),
                "paper_id": paper.get("paper_id"),
                "sources": paper.get("sources"),
            }
            for paper in ranked
        ]
    return result
