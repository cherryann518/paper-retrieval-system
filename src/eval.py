"""
Benchmark evaluation for 1st-baseline retrieval.

Usage:
  python -m src.eval
  python -m src.eval --benchmark data/benchmark/queries.json
  python -m src.eval --rank-method tfidf
  python -m src.eval --no-cache
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.config import DATA_DIR, EVAL_DIR, EMBEDDING_MODEL_NAME, PROJECT_ROOT, embedding_package_version
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
) -> dict:
    try:
        result = run_retrieval(
            query,
            survey_config=config,
            rank_method=rank_method,  # type: ignore[arg-type]
        )
    except Exception as exc:
        print(f"[eval] failed — {query!r}: {exc}", flush=True)
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
            "targets": check_targets([], [], targets),
        }

    metrics = result.get("metrics") or {}
    papers_corpus = result.get("papers") or []
    papers_top10 = result.get("papers_display") or papers_corpus[:10]
    ranked_pool = papers_corpus

    alt_method = "tfidf" if rank_method == "sbert" else "sbert"
    alt_ranked = (
        rank_papers(
            query,
            [dict(p) for p in ranked_pool],
            methods=["sbert", "tfidf", "recency"],
            primary_method=alt_method,  # type: ignore[arg-type]
            from_year=config.timeline_from_year,
            to_year=config.timeline_to_year,
        )
        if ranked_pool and targets
        else []
    )
    alt_targets = check_targets(alt_ranked[:10], alt_ranked, targets)

    return {
        "query": query,
        "category": category,
        "status": result.get("status"),
        "top_score": metrics.get("top_score", 0.0),
        "latency_ms": metrics.get("latency_ms", 0.0),
        "papers_returned": len(papers_top10),
        "pool_size": metrics.get("papers_in_pool", len(ranked_pool)),
        "papers_from_local": metrics.get("papers_from_local", 0),
        "api_calls": metrics.get("api_calls", 0),
        "cache_hits": metrics.get("cache_hits", 0),
        "rank_method": rank_method,
        "targets": check_targets(papers_top10, ranked_pool, targets),
        "targets_alt_rank": {"method": alt_method, **alt_targets},
        "search_query": result.get("search_query"),
    }


def print_summary(rows: list[dict]) -> None:
    header = (
        f"{'query':<32} {'cat':<12} {'top':>5} {'tgt10':>5} {'tgtP':>4} "
        f"{'pool':>5} {'api':>3} {'cch':>3} {'ms':>7} status"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        tgt = row["targets"]
        tgt10 = f"{tgt['found_in_top10']}/{tgt['configured']}" if tgt["configured"] else "-"
        tgt_pool = f"{tgt['found_in_pool']}/{tgt['configured']}" if tgt["configured"] else "-"
        q = row["query"]
        if len(q) > 31:
            q = q[:28] + "..."
        print(
            f"{q:<32} {row.get('category', '-'):<12} "
            f"{row['top_score']:>5.3f} {tgt10:>5} {tgt_pool:>4} "
            f"{row['pool_size']:>5} {row.get('api_calls', 0):>3} "
            f"{row.get('cache_hits', 0):>3} {row['latency_ms']:>7.0f} {row['status']}"
        )


def print_rank_method_recommendation(rows: list[dict], rank_method: str) -> None:
    primary_hits = alt_hits = configured = 0
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"primary": 0, "alt": 0, "n": 0})

    for row in rows:
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
    print(f"\nRank method comparison (top-10 target hits):")
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
        help="Optional eval JSON path (default: outputs/eval/{timestamp}.json)",
    )
    parser.add_argument(
        "--rank-method",
        choices=["sbert", "tfidf", "recency"],
        default=None,
    )
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--official",
        action="store_true",
        help="Publication-style run: forces --no-cache and records reproducibility metadata",
    )
    args = parser.parse_args()

    if not args.benchmark.exists():
        print(f"Benchmark not found: {args.benchmark}", file=sys.stderr)
        sys.exit(1)

    use_cache = not (args.no_cache or args.official)
    if not use_cache:
        set_cache_enabled(False)

    config = SurveyConfig.load()
    rank_method = args.rank_method or config.rank_method
    cases = load_benchmark(args.benchmark)
    rows: list[dict] = []

    print(
        f"Running {len(cases)} queries (rank={rank_method}, cache={'off' if not use_cache else 'on'})\n",
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
            )
        )

    print()
    print_summary(rows)
    print_rank_method_recommendation(rows, rank_method)

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = args.output or EVAL_DIR / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + ".json"
    )
    benchmark_sha = _benchmark_sha256(args.benchmark)
    out_path.write_text(
        json.dumps(
            {
                "benchmark": str(args.benchmark.relative_to(PROJECT_ROOT)),
                "benchmark_sha256": benchmark_sha,
                "rank_method": rank_method,
                "cache_enabled": use_cache,
                "official_run": args.official,
                "embedding_model": EMBEDDING_MODEL_NAME,
                "embedding_package_version": embedding_package_version(),
                "lexical_scorer": LEXICAL_VERSION,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\n[eval] saved → {out_path}", flush=True)


if __name__ == "__main__":
    main()
