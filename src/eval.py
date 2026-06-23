"""
Benchmark evaluation: compare retrieval modes on a fixed query set.

Usage:
  python -m src.eval
  python -m src.eval --benchmark data/benchmark/queries.json
  python -m src.eval --modes single_fetch agent
  python -m src.eval --rank-method tfidf
  python -m src.eval --no-cache
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.agent import run_search_agent
from src.config import DATA_DIR, EVAL_DIR, PROJECT_ROOT
from src.fetch import SurveyConfig
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
    """Report target rank in top-10 results and in the full ranked pool."""
    if not targets:
        return {
            "configured": 0,
            "found_in_top10": 0,
            "found_in_pool": 0,
            "details": [],
        }

    top10_details = _target_ranks(papers_top10, targets)
    pool_details = _target_ranks(ranked_pool, targets)

    details = []
    found_top10 = 0
    found_pool = 0
    for top10_item, pool_item in zip(top10_details, pool_details):
        if top10_item["found"]:
            found_top10 += 1
        if pool_item["found"]:
            found_pool += 1
        details.append(
            {
                "target": top10_item["target"],
                "rank_top10": top10_item["rank"],
                "rank_pool": pool_item["rank"],
                "found_in_top10": top10_item["found"],
                "found_in_pool": pool_item["found"],
            }
        )

    return {
        "configured": len(targets),
        "found_in_top10": found_top10,
        "found_in_pool": found_pool,
        "details": details,
    }


def _batch_top_delta(rounds: list[dict]) -> float | None:
    """Improvement in batch-only top score from first to last round."""
    if len(rounds) < 2:
        return None
    first = rounds[0].get("batch_top_score", 0.0)
    last = rounds[-1].get("batch_top_score", 0.0)
    return round(last - first, 4)


def _alt_rank_targets(
    query: str,
    ranked_pool: list[dict],
    targets: list[dict],
    rank_method: str,
    config: SurveyConfig,
) -> dict:
    if not ranked_pool or not targets:
        return {"found_in_top10": 0, "configured": len(targets)}
    alt_ranked = rank_papers(
        query,
        [dict(p) for p in ranked_pool],
        methods=["sbert", "tfidf", "recency"],
        primary_method=rank_method,  # type: ignore[arg-type]
        from_year=config.timeline_from_year,
        to_year=config.timeline_to_year,
    )
    return check_targets(alt_ranked[:10], alt_ranked, targets)


def load_benchmark(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("benchmark file must be a JSON array")
    return data


def run_eval_case(
    query: str,
    mode: str,
    targets: list[dict],
    category: str,
    *,
    rank_method: str,
    config: SurveyConfig,
) -> dict:
    try:
        result = run_search_agent(
            query,
            mode=mode,
            include_ranked_pool=True,
            survey_config=config,
            rank_method=rank_method,  # type: ignore[arg-type]
        )
    except Exception as exc:
        print(f"[eval] failed {mode!r} — {query!r}: {exc}", flush=True)
        return {
            "query": query,
            "category": category,
            "mode": mode,
            "status": "failure",
            "error": str(exc),
            "top_score": 0.0,
            "top10_good_count": 0,
            "refinement_rounds": 0,
            "ollama_calls": 0,
            "api_calls": 0,
            "cache_hits": 0,
            "latency_ms": 0.0,
            "papers_returned": 0,
            "pool_size": 0,
            "batch_top_delta": None,
            "round0_acceptable": None,
            "rank_method": rank_method,
            "targets": check_targets([], [], targets),
            "targets_alt_rank": {},
            "search_queries_used": [],
            "rounds": [],
        }

    metrics = result.get("metrics") or {}
    rounds = result.get("rounds") or []
    papers_top10 = result.get("papers") or []
    ranked_pool = result.get("ranked_pool") or papers_top10

    alt_method = "tfidf" if rank_method == "sbert" else "sbert"
    alt_targets = _alt_rank_targets(query, ranked_pool, targets, alt_method, config)

    return {
        "query": query,
        "category": category,
        "mode": mode,
        "status": result.get("status"),
        "top_score": metrics.get("top_score", 0.0),
        "top10_good_count": metrics.get("top10_good_count", 0),
        "refinement_rounds": result.get("refinement_rounds", 0),
        "ollama_calls": metrics.get("ollama_calls", 0),
        "api_calls": metrics.get("api_calls", 0),
        "cache_hits": metrics.get("cache_hits", 0),
        "api_calls_semantic_scholar": metrics.get("api_calls_semantic_scholar", 0),
        "api_calls_arxiv": metrics.get("api_calls_arxiv", 0),
        "latency_ms": metrics.get("latency_ms", 0.0),
        "papers_returned": len(papers_top10),
        "pool_size": metrics.get("papers_fetched", len(ranked_pool)),
        "batch_top_delta": _batch_top_delta(rounds),
        "round0_acceptable": rounds[0]["acceptable"] if rounds else None,
        "rank_method": rank_method,
        "scores_by_method": metrics.get("scores_by_method"),
        "targets": check_targets(papers_top10, ranked_pool, targets),
        "targets_alt_rank": {
            "method": alt_method,
            **alt_targets,
        },
        "search_queries_used": result.get("search_queries_used") or [],
        "rounds": rounds,
    }


def print_summary(rows: list[dict]) -> None:
    header = (
        f"{'query':<32} {'cat':<7} {'mode':<16} "
        f"{'top':>5} {'t10g':>4} {'tgt10':>5} {'tgtP':>4} "
        f"{'ref':>3} {'bΔ':>6} {'api':>3} {'cch':>3} {'oll':>3} {'ms':>7} status"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        tgt = row["targets"]
        tgt10 = (
            f"{tgt['found_in_top10']}/{tgt['configured']}"
            if tgt["configured"]
            else "-"
        )
        tgt_pool = (
            f"{tgt['found_in_pool']}/{tgt['configured']}"
            if tgt["configured"]
            else "-"
        )
        batch_delta = row["batch_top_delta"]
        batch_str = f"{batch_delta:+.3f}" if batch_delta is not None else "   -"
        q = row["query"]
        if len(q) > 31:
            q = q[:28] + "..."
        print(
            f"{q:<32} {row.get('category', '-'):<7} {row['mode']:<16} "
            f"{row['top_score']:>5.3f} {row['top10_good_count']:>4} "
            f"{tgt10:>5} {tgt_pool:>4} "
            f"{row['refinement_rounds']:>3} {batch_str:>6} "
            f"{row['api_calls']:>3} {row.get('cache_hits', 0):>3} "
            f"{row['ollama_calls']:>3} "
            f"{row['latency_ms']:>7.0f} {row['status']}"
        )


def print_agent_vs_single(rows: list[dict]) -> None:
    """Highlight queries where agent beat single_fetch on key metrics."""
    by_query: dict[str, dict[str, dict]] = {}
    for row in rows:
        by_query.setdefault(row["query"], {})[row["mode"]] = row

    print("\nAgent vs single_fetch (same query):")
    print(f"{'query':<40} {'winner':<12} note")
    print("-" * 72)
    for query, modes in by_query.items():
        single = modes.get("single_fetch")
        agent = modes.get("agent")
        if not single or not agent:
            continue

        q = query if len(query) <= 39 else query[:36] + "..."
        notes: list[str] = []

        if agent["top_score"] > single["top_score"] + 0.01:
            notes.append(f"top +{agent['top_score'] - single['top_score']:.3f}")
        if agent["top10_good_count"] > single["top10_good_count"]:
            notes.append(f"top10 good +{agent['top10_good_count'] - single['top10_good_count']}")
        if agent["targets"]["found_in_top10"] > single["targets"]["found_in_top10"]:
            notes.append("target→top10")
        elif agent["targets"]["found_in_pool"] > single["targets"]["found_in_pool"]:
            notes.append("target→pool")
        if agent["ollama_calls"] > 0 and single["status"] != "ok" and agent["status"] == "ok":
            notes.append("gate fixed")

        if not notes:
            winner = "tie"
            note = "no clear gain"
            if agent["ollama_calls"] == 0:
                note = "refinement never ran"
        else:
            winner = "agent"
            note = ", ".join(notes)

        print(f"{q:<40} {winner:<12} {note}")


def print_rank_method_recommendation(rows: list[dict], rank_method: str) -> None:
    """Compare primary rank method vs alternate on target hits."""
    primary_hits = 0
    alt_hits = 0
    configured = 0
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"primary": 0, "alt": 0, "n": 0})

    for row in rows:
        if row["mode"] != "single_fetch":
            continue
        tgt = row["targets"]
        alt = row.get("targets_alt_rank") or {}
        if not tgt.get("configured"):
            continue
        configured += tgt["configured"]
        primary_hits += tgt["found_in_top10"]
        alt_hits += alt.get("found_in_top10", 0)
        cat = row.get("category", "-")
        by_category[cat]["n"] += tgt["configured"]
        by_category[cat]["primary"] += tgt["found_in_top10"]
        by_category[cat]["alt"] += alt.get("found_in_top10", 0)

    alt_method = "tfidf" if rank_method == "sbert" else "sbert"
    print(f"\nRank method comparison (single_fetch, top-10 target hits):")
    print(f"  primary ({rank_method}): {primary_hits}/{configured}")
    print(f"  alternate ({alt_method}): {alt_hits}/{configured}")
    if primary_hits >= alt_hits:
        print(f"  recommendation: keep {rank_method} as primary rank method")
    else:
        print(f"  recommendation: consider switching primary to {alt_method}")

    if by_category:
        print("  by category:")
        for cat, stats in sorted(by_category.items()):
            print(
                f"    {cat}: {rank_method}={stats['primary']}/{stats['n']} "
                f"alt={stats['alt']}/{stats['n']}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark paper retrieval modes.")
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=DEFAULT_BENCHMARK,
        help="Path to benchmark queries JSON",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        default=["single_fetch", "multi_fetch_same", "agent"],
        choices=["single_fetch", "multi_fetch_same", "agent"],
        help="Retrieval modes to compare",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for eval JSON (default: outputs/eval/{timestamp}.json)",
    )
    parser.add_argument(
        "--rank-method",
        choices=["sbert", "tfidf", "recency"],
        default=None,
        help="Primary ranking method (default: from survey_config.json)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable source API response cache",
    )
    args = parser.parse_args()

    if not args.benchmark.exists():
        print(f"Benchmark not found: {args.benchmark}", file=sys.stderr)
        sys.exit(1)

    if args.no_cache:
        set_cache_enabled(False)

    config = SurveyConfig.load()
    rank_method = args.rank_method or config.rank_method

    cases = load_benchmark(args.benchmark)
    rows: list[dict] = []

    print(
        f"Running {len(cases)} queries × {len(args.modes)} modes "
        f"(rank={rank_method}, cache={'off' if args.no_cache else 'on'})\n",
        flush=True,
    )
    for case in cases:
        query = (case.get("query") or "").strip()
        if not query:
            continue
        targets = case.get("targets") or []
        category = case.get("category") or "-"
        for mode in args.modes:
            print(f"[eval] {mode!r} — {query!r}", flush=True)
            rows.append(
                run_eval_case(
                    query,
                    mode,
                    targets,
                    category,
                    rank_method=rank_method,
                    config=config,
                )
            )

    print()
    print_summary(rows)

    if "single_fetch" in args.modes and "agent" in args.modes:
        print_agent_vs_single(rows)

    if "single_fetch" in args.modes:
        print_rank_method_recommendation(rows, rank_method)

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = args.output or EVAL_DIR / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + ".json"
    )
    payload = {
        "benchmark": str(args.benchmark.relative_to(PROJECT_ROOT)),
        "modes": args.modes,
        "rank_method": rank_method,
        "cache_enabled": not args.no_cache,
        "rows": rows,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[eval] saved → {out_path}", flush=True)


if __name__ == "__main__":
    main()
