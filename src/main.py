"""
CLI entry point — 1st baseline retrieval.
"""

import argparse
import json
import sys

from src.artifacts import save_run_artifacts
from src.export import export_corpus_ndjson
from src.pipeline import run_retrieval
from src.rank import embed_and_rank
from src.runtime import set_cache_enabled
from src.tools import load_sample_papers

ABSTRACT_MAX_LEN = 300
SEPARATOR = "─" * 72
SOURCE_LABELS = {
    "semantic_scholar": "Semantic Scholar",
    "arxiv": "arXiv",
    "openalex": "OpenAlex",
}


def _format_sources(sources: list[str] | None) -> str:
    if not sources:
        return "unknown"
    return ", ".join(SOURCE_LABELS.get(s, s) for s in sources)


def _truncate(text: str | None, max_len: int = ABSTRACT_MAX_LEN) -> str:
    if not text:
        return "(no abstract)"
    text = text.strip()
    return text if len(text) <= max_len else text[:max_len].rstrip() + "..."


def _print_paper(paper: dict, index: int) -> None:
    authors = ", ".join(paper.get("authors") or []) or "Unknown"
    print(SEPARATOR)
    print(f"{index}. {paper.get('title') or 'Untitled'}")
    print(f"   Authors:  {authors}")
    print(f"   Year:     {paper.get('year') or 'n/a'}")
    print(f"   Source:   {_format_sources(paper.get('sources'))}")
    print(f"   Score:    {paper.get('relevance_score', 0):.4f}")
    print(f"   Abstract: {_truncate(paper.get('abstract'))}")


def _print_metrics(result: dict) -> None:
    m = result.get("metrics") or {}
    print(
        f"Status: {result['status']} | queries={m.get('search_queries_run', 1)} "
        f"(skipped={m.get('search_queries_skipped', 0)}) | "
        f"corpus={m.get('papers_accepted', 0)} accepted "
        f"({m.get('papers_rejected', 0)} rejected) | "
        f"showing {m.get('papers_display', 0)}/{m.get('papers_accepted', 0)} | "
        f"pool={m.get('papers_in_pool', 0)} | top={m.get('top_score', 0):.3f} | "
        f"min_score={m.get('min_relevance_score', 0)} | "
        f"rank={m.get('rank_method')} | api={m.get('api_calls', 0)} | "
        f"{m.get('latency_ms', 0):.0f}ms",
        flush=True,
    )
    if result.get("fetch_errors"):
        print(f"Fetch errors: {len(result['fetch_errors'])} (partial data used)", flush=True)

    qs = m.get("query_state")
    if qs:
        print(
            f"Query state: consecutive_zero_accept={qs.get('consecutive_zero_accept', 0)} | "
            f"last accepted={qs.get('accepted_count', 0)} rejected={qs.get('rejected_count', 0)}",
            flush=True,
        )

    skipped = result.get("skipped_queries") or []
    if skipped:
        print(f"Skipped dead queries ({len(skipped)}):", flush=True)
        for row in skipped:
            print(
                f"  - {row['query']!r} (zero-accept streak={row['consecutive_zero_accept']})",
                flush=True,
            )

    div = m.get("score_divergence") or {}
    if div.get("count"):
        print(
            f"Score divergence (SBERT vs lexical): avg |delta|={div.get('avg_abs_delta', 0):.3f}",
            flush=True,
        )
        for row in div.get("top_divergent") or []:
            title = row["title"]
            if len(title) > 60:
                title = title[:60] + "…"
            print(
                f"  - {title} | sbert={row['sbert_cosine']:.3f} "
                f"lexical={row['lexical_v1']:.3f} delta={row['delta']:+.3f}",
                flush=True,
            )

    if m.get("fts_prefetch_enabled"):
        print(
            f"FTS prefetch: {m.get('papers_from_fts_prefetch', 0)} cross-query hits",
            flush=True,
        )
    flagged = m.get("possible_duplicates_flagged", 0)
    if flagged or m.get("possible_duplicates_total", 0):
        print(
            f"Possible duplicates: +{flagged} flagged this run "
            f"({m.get('possible_duplicates_total', 0)} total in DB)",
            flush=True,
        )
    if m.get("fetch_throttled"):
        print(
            f"Fetch throttled after rate limits (429 events={m.get('rate_limit_errors', 0)})",
            flush=True,
        )
    print(flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search and rank academic papers.")
    parser.add_argument("topic", help="Search topic or keywords")
    parser.add_argument("--offline", action="store_true", help="Use local sample papers")
    parser.add_argument("--no-cache", action="store_true", help="Disable raw API cache")
    parser.add_argument("--no-local", action="store_true", help="Skip local corpus read")
    parser.add_argument(
        "--survey",
        action="store_true",
        help="Run all queries from survey_config (topic, RQs, hints)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON result (includes full RAG corpus)",
    )
    parser.add_argument(
        "--export",
        choices=["ndjson"],
        default=None,
        help="Export accepted corpus to outputs/exports/{run_id}.ndjson",
    )
    args = parser.parse_args()

    topic = args.topic.strip()
    if not topic:
        print("Error: topic must not be empty.", file=sys.stderr)
        sys.exit(1)

    if args.offline:
        print(f"Using sample papers for: {topic!r}\n", flush=True)
        papers = load_sample_papers()
        ranked = embed_and_rank(topic, papers)
        if args.json:
            print(json.dumps({"papers": ranked}, indent=2))
            return
        for i, paper in enumerate(ranked[:10], start=1):
            _print_paper(paper, i)
        return

    if args.no_cache:
        set_cache_enabled(False)

    print(f"Searching for: {topic!r}\n", flush=True)
    result = run_retrieval(
        topic,
        use_local_corpus=not args.no_local,
        survey_mode=args.survey,
    )
    run_dir = save_run_artifacts(result)
    print(f"Artifacts: {run_dir}\n", flush=True)

    if args.export == "ndjson":
        export_path = run_dir / "corpus.ndjson"
        export_corpus_ndjson(result, export_path)
        print(f"Exported corpus → {export_path}\n", flush=True)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    _print_metrics(result)
    display = result.get("papers_display") or []
    corpus = result.get("papers") or []

    if not display and not corpus:
        print("No papers found.")
        if result["status"] == "failure":
            sys.exit(1)
        return

    print(f"Preview: top {len(display)} of {len(corpus)} accepted papers:\n")
    for i, paper in enumerate(display, start=1):
        _print_paper(paper, i)
    if len(corpus) > len(display):
        print(
            f"\n{SEPARATOR}\n"
            f"Full corpus ({len(corpus)} papers) saved in run artifacts / use --json.\n"
            f"{SEPARATOR}"
        )
    else:
        print(f"\n{SEPARATOR}")


if __name__ == "__main__":
    main()
