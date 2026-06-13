"""
Agentic search loop: retrieve, score, optionally refine query via Ollama.
"""

import json
import urllib.error
import urllib.request

from src.config import (
    MAX_PAPERS_PER_SEARCH,
    MAX_REFINEMENT_ROUNDS,
    MIN_GOOD_PAPERS,
    MIN_SCORE_GAP,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    SCORE_GOOD,
    SCORE_TOP_MIN,
)
from src.tools import SemanticScholarError, embed_and_rank, search_semantic_scholar

OLLAMA_SYSTEM_PROMPT = """You help refine academic paper search queries for Semantic Scholar.

Rules:
- Output ONLY a single search query string on one line.
- No quotes, no explanation, no JSON, no bullet points.
- Stay in the same research area as the original user topic.
- If results were irrelevant, broaden or rephrase using standard academic terms.
- If results were too narrow or off-topic, simplify or use synonyms.
- Prefer 3-8 words. Use field-specific keywords when helpful.
- Do not invent paper titles or author names."""


class OllamaError(Exception):
    """Raised when the local Ollama API is unavailable or returns an error."""


def _paper_key(paper: dict) -> str:
    ids = paper.get("externalIds") or {}
    if ids.get("DOI"):
        return f"doi:{ids['DOI'].lower()}"
    if ids.get("arXiv"):
        return f"arxiv:{ids['arXiv'].lower()}"
    return f"title:{(paper.get('title') or '').strip().lower()}"


def dedupe_papers(papers: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for paper in papers:
        key = _paper_key(paper)
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


def _format_results_for_prompt(ranked: list[dict], limit: int = 5) -> str:
    lines = []
    for index, paper in enumerate(ranked[:limit], start=1):
        title = paper.get("title") or "Untitled"
        score = paper.get("relevance_score", 0)
        lines.append(f"{index}. {title} | {score:.3f}")
    return "\n".join(lines) if lines else "(no results)"


def _parse_refined_query(raw: str) -> str:
    query = raw.strip().split("\n")[0].strip().strip("\"'")
    if not query or len(query) > 120:
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
    user_prompt = f"""Original user topic: {original_query}
Why results were rejected: {reason}
Previous search query: {search_query}
Refinement attempt: {refinement_round} of {MAX_REFINEMENT_ROUNDS}

Top retrieved papers (may be weak matches):
{_format_results_for_prompt(ranked)}

Write one improved Semantic Scholar search query."""

    raw = _ollama_generate(OLLAMA_SYSTEM_PROMPT, user_prompt)
    try:
        return _parse_refined_query(raw)
    except ValueError:
        retry_prompt = user_prompt + "\n\nOutput only the query string on one line."
        raw = _ollama_generate(OLLAMA_SYSTEM_PROMPT, retry_prompt)
        return _parse_refined_query(raw)


def run_search_agent(original_query: str) -> dict:
    """
    Search Semantic Scholar, rank by relevance, and refine the query via Ollama
    when results fail acceptance thresholds (up to MAX_REFINEMENT_ROUNDS times).
    """
    if not original_query or not original_query.strip():
        raise ValueError("query must be a non-empty string")

    original_query = original_query.strip()
    search_query = original_query
    all_papers: list[dict] = []
    search_queries_used: list[str] = []
    refinement_round = 0
    ranked: list[dict] = []
    reason = "no_papers"

    while refinement_round <= MAX_REFINEMENT_ROUNDS:
        print(
            f"[agent] round={refinement_round} search_query={search_query!r}",
            flush=True,
        )
        batch = search_semantic_scholar(search_query, limit=MAX_PAPERS_PER_SEARCH)
        search_queries_used.append(search_query)
        all_papers = dedupe_papers(all_papers + batch)
        ranked = embed_and_rank(original_query, all_papers)

        ok, reason = results_acceptable(ranked)
        print(f"[agent] acceptable={ok} reason={reason}", flush=True)

        if ok:
            return {
                "query": original_query,
                "papers": ranked[:MAX_PAPERS_PER_SEARCH],
                "status": "ok",
                "refinement_rounds": refinement_round,
                "search_queries_used": search_queries_used,
                "acceptance_reason": reason,
            }

        if refinement_round >= MAX_REFINEMENT_ROUNDS:
            break

        try:
            search_query = ollama_refine_query(
                original_query,
                search_query,
                ranked,
                reason,
                refinement_round + 1,
            )
            print(f"[agent] refined query={search_query!r}", flush=True)
        except OllamaError as exc:
            print(f"[agent] Ollama unavailable: {exc}", flush=True)
            break

        refinement_round += 1

    return {
        "query": original_query,
        "papers": ranked[:MAX_PAPERS_PER_SEARCH],
        "status": "weak_results",
        "refinement_rounds": refinement_round,
        "search_queries_used": search_queries_used,
        "acceptance_reason": reason,
    }
