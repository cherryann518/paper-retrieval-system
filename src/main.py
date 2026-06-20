"""
Entry point for the paper retrieval system.

Search Semantic Scholar for a topic, rank results by semantic relevance,
and print a readable summary to the terminal.
"""

import argparse
import sys

from src.agent import run_search_agent
from src.artifacts import save_run_artifacts
from src.tools import embed_and_rank, load_sample_papers

ABSTRACT_MAX_LEN = 300
SEPARATOR = "─" * 72


def _truncate(text: str | None, max_len: int = ABSTRACT_MAX_LEN) -> str:
    if not text:
        return "(no abstract)"
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "..."


def _format_authors(authors: list[str] | None) -> str:
    if not authors:
        return "Unknown"
    return ", ".join(authors)


def _print_paper(paper: dict, index: int) -> None:
    print(SEPARATOR)
    print(f"{index}. {paper.get('title') or 'Untitled'}")
    print(f"   Authors:  {_format_authors(paper.get('authors'))}")
    print(f"   Year:     {paper.get('year') or 'n/a'}")
    print(f"   Score:    {paper.get('relevance_score', 0):.4f}")
    print(f"   Abstract: {_truncate(paper.get('abstract'))}")


def _print_metrics(result: dict) -> None:
    metrics = result.get("metrics") or {}
    rounds = result.get("rounds") or []
    print(
        f"Status: {result['status']} | "
        f"refinements: {result.get('refinement_rounds', 0)} | "
        f"reason: {result.get('acceptance_reason', '')}",
        flush=True,
    )
    print(
        f"Metrics: top={metrics.get('top_score', 0):.3f} | "
        f"good={metrics.get('good_count', 0)} | "
        f"api={metrics.get('api_calls', 0)} | "
        f"ollama={metrics.get('ollama_calls', 0)} | "
        f"{metrics.get('latency_ms', 0):.0f}ms",
        flush=True,
    )
    if rounds:
        print("Rounds:", flush=True)
        for record in rounds:
            print(
                f"  [{record['round']}] query={record['search_query']!r} "
                f"batch={record['batch_size']} pool={record['pool_size']} "
                f"top={record['top_score']:.3f} "
                f"batch_top={record.get('batch_top_score', 0):.3f} "
                f"ok={record['acceptable']}",
                flush=True,
            )
    if result.get("fetch_errors"):
        print(f"Fetch errors: {len(result['fetch_errors'])} (partial data used)", flush=True)
    print(flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search and rank academic papers by semantic relevance."
    )
    parser.add_argument("topic", help="Search topic or keywords")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use local sample papers instead of Semantic Scholar (avoids API rate limits)",
    )
    parser.add_argument(
        "--mode",
        choices=["agent", "single_fetch", "multi_fetch_same"],
        default="agent",
        help="Retrieval mode (live search only)",
    )
    parser.add_argument(
        "--no-refine",
        action="store_true",
        help="Disable Ollama query refinement (agent mode only)",
    )
    args = parser.parse_args()

    topic = args.topic.strip()
    if not topic:
        print("Error: topic must not be empty.", file=sys.stderr)
        sys.exit(1)

    if args.offline:
        print(f"Using sample papers for: {topic!r}\n", flush=True)
        papers = load_sample_papers()
        if not papers:
            print("No papers found.")
            return
        ranked = embed_and_rank(topic, papers)
        print(f"Found {len(ranked)} papers, sorted by relevance...\n")
    else:
        print(f"Running search ({args.mode}) for: {topic!r}\n", flush=True)
        result = run_search_agent(
            topic,
            mode=args.mode,
            refine=not args.no_refine,
        )
        run_dir = save_run_artifacts(result)
        print(f"Artifacts: {run_dir}\n", flush=True)
        _print_metrics(result)
        ranked = result["papers"]
        if not ranked:
            print("No papers found.")
            if result["status"] == "failure":
                sys.exit(1)
            return
        print(f"Found {len(ranked)} papers, sorted by relevance...\n")

    for index, paper in enumerate(ranked, start=1):
        _print_paper(paper, index)

    print(f"\n{SEPARATOR}")


if __name__ == "__main__":
    main()
