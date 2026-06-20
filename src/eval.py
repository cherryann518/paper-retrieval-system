"""
Benchmark evaluation: compare retrieval modes on a fixed query set.

Usage:
  python -m src.eval
  python -m src.eval --benchmark data/benchmark/queries.json
  python -m src.eval --modes single_fetch agent multi_fetch_same
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.agent import run_search_agent
from src.config import DATA_DIR, EVAL_DIR, PROJECT_ROOT

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


def load_benchmark(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("benchmark file must be a JSON array")
    return data


def run_eval_case(query: str, mode: str, targets: list[dict], category: str) -> dict:
    try:
        result = run_search_agent(query, mode=mode, include_ranked_pool=True)
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
            "latency_ms": 0.0,
            "papers_returned": 0,
            "pool_size": 0,
            "batch_top_delta": None,
            "round0_acceptable": None,
            "targets": check_targets([], [], targets),
            "search_queries_used": [],
            "rounds": [],
        }

    metrics = result.get("metrics") or {}
    rounds = result.get("rounds") or []
    papers_top10 = result.get("papers") or []
    ranked_pool = result.get("ranked_pool") or papers_top10

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
        "latency_ms": metrics.get("latency_ms", 0.0),
        "papers_returned": len(papers_top10),
        "pool_size": metrics.get("papers_fetched", len(ranked_pool)),
        "batch_top_delta": _batch_top_delta(rounds),
        "round0_acceptable": rounds[0]["acceptable"] if rounds else None,
        "targets": check_targets(papers_top10, ranked_pool, targets),
        "search_queries_used": result.get("search_queries_used") or [],
        "rounds": rounds,
    }


def print_summary(rows: list[dict]) -> None:
    header = (
        f"{'query':<32} {'cat':<7} {'mode':<16} "
        f"{'top':>5} {'t10g':>4} {'tgt10':>5} {'tgtP':>4} "
        f"{'ref':>3} {'bΔ':>6} {'api':>3} {'oll':>3} {'ms':>7} status"
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
            f"{row['api_calls']:>3} {row['ollama_calls']:>3} "
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
    args = parser.parse_args()

    if not args.benchmark.exists():
        print(f"Benchmark not found: {args.benchmark}", file=sys.stderr)
        sys.exit(1)

    cases = load_benchmark(args.benchmark)
    rows: list[dict] = []

    print(f"Running {len(cases)} queries × {len(args.modes)} modes\n", flush=True)
    for case in cases:
        query = (case.get("query") or "").strip()
        if not query:
            continue
        targets = case.get("targets") or []
        category = case.get("category") or "-"
        for mode in args.modes:
            print(f"[eval] {mode!r} — {query!r}", flush=True)
            rows.append(run_eval_case(query, mode, targets, category))

    print()
    print_summary(rows)

    if "single_fetch" in args.modes and "agent" in args.modes:
        print_agent_vs_single(rows)

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = args.output or EVAL_DIR / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + ".json"
    )
    payload = {
        "benchmark": str(args.benchmark.relative_to(PROJECT_ROOT)),
        "modes": args.modes,
        "rows": rows,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[eval] saved → {out_path}", flush=True)


if __name__ == "__main__":
    main()
