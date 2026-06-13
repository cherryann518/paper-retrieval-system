"""
Entry point for the paper retrieval system.

Search Semantic Scholar for a topic, rank results by semantic relevance,
and print a readable summary to the terminal.
"""

import argparse
import sys

from src.agent import run_search_agent
from src.tools import SemanticScholarError, embed_and_rank, load_sample_papers

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
        print(f"Running search agent for: {topic!r}\n", flush=True)
        try:
            result = run_search_agent(topic)
        except SemanticScholarError as exc:
            print(f"Search failed: {exc}", file=sys.stderr)
            sys.exit(1)
        ranked = result["papers"]
        print(
            f"Status: {result['status']} | "
            f"refinements: {result['refinement_rounds']} | "
            f"reason: {result['acceptance_reason']}\n",
            flush=True,
        )
        if not ranked:
            print("No papers found.")
            return
        print(f"Found {len(ranked)} papers, sorted by relevance...\n")

    for index, paper in enumerate(ranked, start=1):
        _print_paper(paper, index)

    print(f"\n{SEPARATOR}")


if __name__ == "__main__":
    main()
