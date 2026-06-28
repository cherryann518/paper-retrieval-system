"""
Benchmark evaluation for 1st-baseline retrieval.

Usage:
  python -m src.eval
  python -m src.eval --benchmark data/benchmark/queries.json
  python -m src.eval --rank-method tfidf
  python -m src.eval --no-cache
  python -m src.eval --official
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import (
    DATA_DIR,
    EVAL_DIR,
    EMBEDDING_MODEL_NAME,
    OFFICIAL_BASELINE_PATH,
    PROJECT_ROOT,
    embedding_package_version,
)
from src.fetch import SurveyConfig
from src.lexical import LEXICAL_VERSION
from src.pipeline import run_retrieval
from src.rank import rank_papers
from src.runtime import set_cache_enabled

DEFAULT_BENCHMARK = DATA_DIR / "benchmark" / "queries.json"


def _normalize_title(title: str) -> str:
    return " ".join((title or "").lower().split())


def _paper_matches_target(paper: dict, target: dict) -> bool:
    ids = paper.get("externalIds") or {}
    if target.get("doi") and ids.get("DOI"):
        if ids["DOI"].lower() == target["doi"].lower():
            return True
    if target.get("arxiv") and ids.get("arXiv"):
        if ids["arXiv"].lower() == target["arxiv"].lower():
            return True
    if target.get("title"):
        if _normalize_title(paper.get("title") or "") == _normalize_title(target["title"]):
            return True
    return False


def _target_ranks(papers: list[dict], targets: list[dict]) -> list[dict]:
    details = []
    for target in targets:
        rank = None
        for index, paper in enumerate(papers, start=1):
            if _paper_matches_target(paper, target):
                rank = index
                break
        details.append({"target": target, "rank": rank, "found": rank is not None})
    return details


def check_targets(
    papers_top10: list[dict],
    ranked_pool: list[dict],
    targets: list[dict],
) -> dict:
    if not targets:
        return {"configured": 0, "found_in_top10": 0, "found_in_pool": 0, "details": []}

    top10_details = _target_ranks(papers_top10, targets)
    pool_details = _target_ranks(ranked_pool, targets)
    details = []
    found_top10 = found_pool = 0
    for t10, pool in zip(top10_details, pool_details):
        if t10["found"]:
            found_top10 += 1
        if pool["found"]:
            found_pool += 1
        details.append(
            {
                "target": t10["target"],
                "rank_top10": t10["rank"],
                "rank_pool": pool["rank"],
                "found_in_top10": t10["found"],
                "found_in_pool": pool["found"],
            }
        )
    return {
        "configured": len(targets),
        "found_in_top10": found_top10,
        "found_in_pool": found_pool,
        "details": details,
    }


def check_targets_full(
    *,
    targets: list[dict],
    display: list[dict],
    ranked_pool: list[dict],
    accepted: list[dict],
    rejects: list[dict],
) -> dict[str, Any]:
    """C1 — separate retrieval pool vs accepted corpus vs screening rejects."""
    display_top10 = display[:10]
    accepted_top10 = accepted[:10]
    reject_papers = [
        {
            "title": r.get("title"),
            "paper_id": r.get("paper_id"),
            "externalIds": {},
            "relevance_score": r.get("relevance_score"),
        }
        for r in rejects
    ]
    return {
        "display": check_targets(display_top10, display, targets),
        "ranked_pool": check_targets(ranked_pool[:10], ranked_pool, targets),
        "accepted": check_targets(accepted_top10, accepted, targets),
        "rejects": check_targets([], reject_papers, targets),
    }


def _count_targets_in_rejects(targets: dict) -> int:
    return targets.get("rejects", {}).get("found_in_pool", 0)


def _benchmark_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_benchmark(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("benchmark file must be a JSON array")
    return data


def run_eval_case(
    query: str,
    targets: list[dict],
    category: str,
    *,
    rank_method: str,
    config: SurveyConfig,
    config_overrides: dict[str, Any] | None = None,
    use_local_corpus: bool = True,
    skip_screening: bool = False,
) -> dict:
    merged_overrides = {**(config_overrides or {})}
    try:
        result = run_retrieval(
            query,
            survey_config=config,
            config_overrides=merged_overrides or None,
            rank_method=rank_method,  # type: ignore[arg-type]
            use_local_corpus=use_local_corpus,
            skip_screening=skip_screening,
        )
    except Exception as exc:
        print(f"[eval] failed — {query!r}: {exc}", flush=True)
        empty = check_targets_full(
            targets=targets,
            display=[],
            ranked_pool=[],
            accepted=[],
            rejects=[],
        )
        return {
            "query": query,
            "category": category,
            "status": "failure",
            "error": str(exc),
            "top_score": 0.0,
            "latency_ms": 0.0,
            "papers_returned": 0,
            "pool_size": 0,
            "rank_method": rank_method,
            "targets": empty,
        }

    metrics = result.get("metrics") or {}
    ranked_pool = result.get("ranked_pool") or []
    papers_accepted = result.get("papers") or []
    papers_display = result.get("papers_display") or papers_accepted[:10]
    rejects = result.get("rejects") or []

    case_config = config.apply_overrides(merged_overrides or None)
    alt_method = "tfidf" if rank_method == "sbert" else "sbert"
    alt_ranked = (
        rank_papers(
            query,
            [dict(p) for p in ranked_pool],
            methods=["sbert", "tfidf", "recency"],
            primary_method=alt_method,  # type: ignore[arg-type]
            from_year=case_config.timeline_from_year,
            to_year=case_config.timeline_to_year,
        )
        if ranked_pool and targets
        else []
    )

    target_report = check_targets_full(
        targets=targets,
        display=papers_display,
        ranked_pool=ranked_pool,
        accepted=papers_accepted,
        rejects=rejects,
    )

    div_pool = (metrics.get("score_divergence_pool") or {}).get("avg_abs_delta", 0.0)

    return {
        "query": query,
        "category": category,
        "status": result.get("status"),
        "top_score": metrics.get("top_score", 0.0),
        "latency_ms": metrics.get("latency_ms", 0.0),
        "papers_returned": len(papers_display),
        "papers_accepted": len(papers_accepted),
        "papers_ranked": len(ranked_pool),
        "papers_rejected": len(rejects),
        "pool_size": metrics.get("papers_in_pool", len(ranked_pool)),
        "papers_from_local": metrics.get("papers_from_local", 0),
        "papers_from_fts": metrics.get("papers_from_fts_prefetch", 0),
        "possible_duplicates_flagged": metrics.get("possible_duplicates_flagged", 0),
        "divergence_avg": div_pool,
        "targets_rejected": _count_targets_in_rejects(target_report),
        "api_calls": metrics.get("api_calls", 0),
        "cache_hits": metrics.get("cache_hits", 0),
        "rank_method": rank_method,
        "skip_screening": skip_screening,
        "config_overrides": merged_overrides or None,
        "targets": target_report,
        "targets_alt_rank": {
            "method": alt_method,
            **check_targets(alt_ranked[:10], alt_ranked, targets),
        },
        "search_query": result.get("search_query"),
    }


def _aggregate_summary(rows: list[dict]) -> dict[str, Any]:
    configured = pool_hits = accept_hits = display_hits = 0
    for row in rows:
        tgt = row.get("targets") or {}
        for key in ("ranked_pool", "accepted", "display"):
            block = tgt.get(key) or {}
            if key == "ranked_pool":
                pool_hits += block.get("found_in_pool", 0)
            elif key == "accepted":
                accept_hits += block.get("found_in_pool", 0)
            else:
                display_hits += block.get("found_in_top10", 0)
        rp = tgt.get("ranked_pool") or {}
        configured += rp.get("configured", 0)
    return {
        "target_slots": configured,
        "hits_display_top10": display_hits,
        "hits_ranked_pool": pool_hits,
        "hits_accepted_corpus": accept_hits,
        "queries": len(rows),
    }


def print_summary(rows: list[dict]) -> None:
    header = (
        f"{'query':<28} {'cat':<10} {'top':>5} "
        f"{'dsp':>4} {'pool':>4} {'acc':>4} {'rej':>3} "
        f"{'div':>5} {'fts':>3} {'dup':>3} "
        f"{'api':>3} {'ms':>6} status"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        tgt = row.get("targets") or {}
        dsp = tgt.get("display") or {}
        pool = tgt.get("ranked_pool") or {}
        acc = tgt.get("accepted") or {}
        configured = pool.get("configured") or dsp.get("configured") or 0
        dsp_s = (
            f"{dsp.get('found_in_top10', 0)}/{configured}" if configured else "-"
        )
        pool_s = (
            f"{pool.get('found_in_pool', 0)}/{configured}" if configured else "-"
        )
        acc_s = (
            f"{acc.get('found_in_pool', 0)}/{configured}" if configured else "-"
        )
        q = row["query"]
        if len(q) > 27:
            q = q[:24] + "..."
        print(
            f"{q:<28} {row.get('category', '-'):<10} "
            f"{row['top_score']:>5.3f} {dsp_s:>4} {pool_s:>4} {acc_s:>4} "
            f"{row.get('targets_rejected', 0):>3} "
            f"{row.get('divergence_avg', 0):>5.3f} "
            f"{row.get('papers_from_fts', 0):>3} "
            f"{row.get('possible_duplicates_flagged', 0):>3} "
            f"{row.get('api_calls', 0):>3} "
            f"{row['latency_ms']:>6.0f} {row['status']}"
        )
    print(
        "\nColumns: dsp=target@display top10 | pool=target@pre-screen ranked | "
        "acc=target@accepted corpus | rej=targets lost to screening"
    )


def print_rank_method_recommendation(rows: list[dict], rank_method: str) -> None:
    primary_hits = alt_hits = configured = 0
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"primary": 0, "alt": 0, "n": 0})

    for row in rows:
        tgt = row.get("targets") or {}
        pool = tgt.get("ranked_pool") or {}
        alt = row.get("targets_alt_rank") or {}
        if not pool.get("configured"):
            continue
        configured += pool["configured"]
        primary_hits += pool.get("found_in_pool", 0)
        alt_hits += alt.get("found_in_pool", 0)
        cat = row.get("category", "-")
        by_category[cat]["n"] += pool["configured"]
        by_category[cat]["primary"] += pool.get("found_in_pool", 0)
        by_category[cat]["alt"] += alt.get("found_in_pool", 0)

    alt_method = "tfidf" if rank_method == "sbert" else "sbert"
    print(f"\nRank method comparison (pre-screen pool target hits):")
    print(f"  primary ({rank_method}): {primary_hits}/{configured}")
    print(f"  alternate ({alt_method}): {alt_hits}/{configured}")
    if by_category:
        print("  by category:")
        for cat, stats in sorted(by_category.items()):
            print(
                f"    {cat}: {rank_method}={stats['primary']}/{stats['n']} "
                f"alt={stats['alt']}/{stats['n']}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark paper retrieval.")
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional eval JSON path (default: timestamp or OFFICIAL_BASELINE.json)",
    )
    parser.add_argument(
        "--rank-method",
        choices=["sbert", "tfidf", "recency"],
        default=None,
    )
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--no-local",
        action="store_true",
        help="Skip local corpus read (recommended for reproducible eval)",
    )
    parser.add_argument(
        "--skip-screening",
        action="store_true",
        help="Measure retrieval only (no min_score / dual-gate rejects)",
    )
    parser.add_argument(
        "--official",
        action="store_true",
        help="Publication run: --no-cache + --no-local; writes OFFICIAL_BASELINE.json",
    )
    args = parser.parse_args()

    if not args.benchmark.exists():
        print(f"Benchmark not found: {args.benchmark}", file=sys.stderr)
        sys.exit(1)

    official = args.official
    use_cache = not (args.no_cache or official)
    use_local = not (args.no_local or official)
    skip_screening = args.skip_screening

    if not use_cache:
        set_cache_enabled(False)

    config = SurveyConfig.load()
    rank_method = args.rank_method or config.rank_method
    cases = load_benchmark(args.benchmark)
    rows: list[dict] = []

    print(
        f"Running {len(cases)} queries (rank={rank_method}, "
        f"cache={'off' if not use_cache else 'on'}, "
        f"local={'off' if not use_local else 'on'}, "
        f"screening={'off' if skip_screening else 'on'})\n",
        flush=True,
    )
    for case in cases:
        query = (case.get("query") or "").strip()
        if not query:
            continue
        print(f"[eval] — {query!r}", flush=True)
        rows.append(
            run_eval_case(
                query,
                case.get("targets") or [],
                case.get("category") or "-",
                rank_method=rank_method,
                config=config,
                config_overrides=case.get("config"),
                use_local_corpus=use_local,
                skip_screening=skip_screening,
            )
        )

    print()
    print_summary(rows)
    print_rank_method_recommendation(rows, rank_method)
    summary = _aggregate_summary(rows)
    print(
        f"\nAggregate: pool hits={summary['hits_ranked_pool']}/{summary['target_slots']} | "
        f"accepted hits={summary['hits_accepted_corpus']}/{summary['target_slots']} | "
        f"display hits={summary['hits_display_top10']}/{summary['target_slots']}"
    )

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    if args.output:
        out_path = args.output
    elif official:
        out_path = OFFICIAL_BASELINE_PATH
    else:
        out_path = EVAL_DIR / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + ".json"
        )

    benchmark_sha = _benchmark_sha256(args.benchmark)
    payload = {
        "benchmark": str(args.benchmark.relative_to(PROJECT_ROOT)),
        "benchmark_sha256": benchmark_sha,
        "rank_method": rank_method,
        "cache_enabled": use_cache,
        "local_corpus_enabled": use_local,
        "skip_screening": skip_screening,
        "official_run": official,
        "embedding_model": EMBEDDING_MODEL_NAME,
        "embedding_package_version": embedding_package_version(),
        "lexical_scorer": LEXICAL_VERSION,
        "aggregate": summary,
        "rows": rows,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[eval] saved → {out_path}", flush=True)


if __name__ == "__main__":
    main()
