"""
Utility functions for paper retrieval.

Provides helpers for querying external sources (e.g. arXiv, Semantic Scholar,
PubMed), normalizing metadata (title, authors, abstract, PDF links), deduplicating
results, and saving retrieved papers to data/ or outputs/.
"""

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request

from src.config import DATA_DIR, SEMANTIC_SCHOLAR_API_KEY, SEMANTIC_SCHOLAR_MIN_INTERVAL

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
SEMANTIC_SCHOLAR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_TIMEOUT = 30
SEMANTIC_SCHOLAR_MAX_RETRIES = 6
SEMANTIC_SCHOLAR_INITIAL_BACKOFF = 2.0

_last_s2_request_at = 0.0


class SemanticScholarError(Exception):
    """Raised when a Semantic Scholar API request fails."""


def _wait_for_s2_rate_limit() -> None:
    """Enforce 1 request/sec when an API key is configured."""
    global _last_s2_request_at
    if not SEMANTIC_SCHOLAR_API_KEY:
        return
    elapsed = time.monotonic() - _last_s2_request_at
    if elapsed < SEMANTIC_SCHOLAR_MIN_INTERVAL:
        time.sleep(SEMANTIC_SCHOLAR_MIN_INTERVAL - elapsed)


def _s2_request_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "PaperRetrievalSystem/1.0",
    }
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
    return headers


_embedding_model = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def _paper_text(paper: dict) -> str:
    title = paper.get("title") or ""
    abstract = paper.get("abstract") or ""
    return f"{title} {abstract}".strip()


def embed_and_rank(query: str, papers: list[dict]) -> list[dict]:
    """
    Embed *query* and each paper's title + abstract, score by cosine similarity,
    add a relevance_score to each paper dict, and return papers sorted descending.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not papers:
        return []

    from sentence_transformers.util import cos_sim

    model = _get_embedding_model()
    query_embedding = model.encode(query.strip(), convert_to_tensor=True)
    paper_embeddings = model.encode(
        [_paper_text(paper) for paper in papers],
        convert_to_tensor=True,
    )
    scores = cos_sim(query_embedding, paper_embeddings)[0].tolist()

    for paper, score in zip(papers, scores):
        paper["relevance_score"] = float(score)

    return sorted(papers, key=lambda paper: paper["relevance_score"], reverse=True)


def search_semantic_scholar(query: str, limit: int = 5) -> list[dict]:
    """
    Search Semantic Scholar for papers matching *query*.

    Returns a list of dicts with keys: title, authors, year, abstract, externalIds.
    externalIds contains arXiv and DOI when available.

    Raises:
        ValueError: If query is empty or limit is invalid.
        SemanticScholarError: On network, HTTP, or parse failures.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    if limit < 1:
        raise ValueError("limit must be at least 1")

    params = urllib.parse.urlencode(
        {
            "query": query.strip(),
            "limit": limit,
            "fields": "title,authors,year,abstract,externalIds",
        }
    )
    url = f"{SEMANTIC_SCHOLAR_SEARCH_URL}?{params}"
    request = urllib.request.Request(url, headers=_s2_request_headers())

    payload = None
    last_error: SemanticScholarError | None = None

    for attempt in range(SEMANTIC_SCHOLAR_MAX_RETRIES + 1):
        try:
            _wait_for_s2_rate_limit()
            with urllib.request.urlopen(request, timeout=SEMANTIC_SCHOLAR_TIMEOUT) as response:
                payload = json.loads(response.read().decode())
            _last_s2_request_at = time.monotonic()
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            try:
                message = json.loads(body).get("message", body)
            except json.JSONDecodeError:
                message = body or exc.reason
            last_error = SemanticScholarError(f"HTTP {exc.code}: {message}")

            if exc.code == 429 and attempt < SEMANTIC_SCHOLAR_MAX_RETRIES:
                retry_after = exc.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait = float(retry_after)
                elif SEMANTIC_SCHOLAR_API_KEY:
                    wait = SEMANTIC_SCHOLAR_MIN_INTERVAL
                else:
                    wait = min(
                        SEMANTIC_SCHOLAR_INITIAL_BACKOFF * (2**attempt),
                        60.0,
                    )
                    wait *= random.uniform(1.0, 1.5)
                time.sleep(wait)
                continue

            raise last_error from exc
        except urllib.error.URLError as exc:
            raise SemanticScholarError(f"Request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise SemanticScholarError("Invalid JSON response from Semantic Scholar API") from exc

    if payload is None:
        raise last_error or SemanticScholarError("Request failed after retries")

    papers = []
    for item in payload.get("data", []):
        raw_ids = item.get("externalIds") or {}
        papers.append(
            {
                "title": item.get("title"),
                "authors": [
                    author["name"]
                    for author in (item.get("authors") or [])
                    if author.get("name")
                ],
                "year": item.get("year"),
                "abstract": item.get("abstract"),
                "externalIds": {
                    "arXiv": raw_ids.get("ArXiv"),
                    "DOI": raw_ids.get("DOI"),
                },
            }
        )
    return papers


def load_sample_papers(limit: int | None = None) -> list[dict]:
    """Load offline sample papers for debugging and testing only."""
    path = DATA_DIR / "sample_papers.json"
    with path.open(encoding="utf-8") as f:
        papers = json.load(f)
    if limit is not None:
        return papers[:limit]
    return papers


def search_papers(query: str, max_results: int = 10) -> list[dict]:
    """Search Semantic Scholar for papers. Raises SemanticScholarError on failure."""
    return search_semantic_scholar(query, limit=max_results)


def download_paper(paper_id: str, destination: str) -> None:
    # TODO: fetch and save PDF or metadata for a given paper
    pass
