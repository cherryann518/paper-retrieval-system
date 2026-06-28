"""
Semantic Scholar source adapter.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from src.cache import get_cached, is_cache_enabled, make_cache_key, set_cached
from src.config import SEMANTIC_SCHOLAR_API_KEY, SEMANTIC_SCHOLAR_MIN_INTERVAL

SEMANTIC_SCHOLAR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_TIMEOUT = 30
SEMANTIC_SCHOLAR_MAX_RETRIES = 6
SEMANTIC_SCHOLAR_INITIAL_BACKOFF = 2.0
SEMANTIC_SCHOLAR_FIELDS = (
    "paperId,corpusId,url,title,authors,year,abstract,externalIds,"
    "venue,citationCount,openAccessPdf,publicationDate"
)

_last_s2_request_at = 0.0


class SemanticScholarError(Exception):
    """Raised when a Semantic Scholar API request fails."""


def _wait_for_s2_rate_limit() -> None:
    global _last_s2_request_at
    if not SEMANTIC_SCHOLAR_API_KEY:
        return
    elapsed = time.monotonic() - _last_s2_request_at
    if elapsed < SEMANTIC_SCHOLAR_MIN_INTERVAL:
        time.sleep(SEMANTIC_SCHOLAR_MIN_INTERVAL - elapsed)


def _s2_headers() -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "PaperRetrievalSystem/1.0"}
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
    return headers


def _parse_s2_papers(payload: dict[str, Any]) -> list[dict]:
    papers = []
    for item in payload.get("data", []):
        raw_ids = item.get("externalIds") or {}
        oa_pdf = item.get("openAccessPdf") or {}
        papers.append(
            {
                "paperId": item.get("paperId"),
                "title": item.get("title"),
                "authors": [
                    a["name"] for a in (item.get("authors") or []) if a.get("name")
                ],
                "year": item.get("year"),
                "abstract": item.get("abstract"),
                "venue": item.get("venue"),
                "citationCount": item.get("citationCount"),
                "externalIds": {"arXiv": raw_ids.get("ArXiv"), "DOI": raw_ids.get("DOI")},
                "pdf_url": oa_pdf.get("url") if isinstance(oa_pdf, dict) else None,
            }
        )
    return papers


def search_semantic_scholar(
    query: str,
    limit: int = 100,
    offset: int = 0,
    *,
    year: str | None = None,
    fields_of_study: str | None = None,
) -> tuple[list[dict], bool]:
    params: dict[str, Any] = {
        "query": query.strip(),
        "limit": limit,
        "offset": offset,
        "fields": SEMANTIC_SCHOLAR_FIELDS,
    }
    if year:
        params["year"] = year
    if fields_of_study:
        params["fieldsOfStudy"] = fields_of_study

    cache_key = make_cache_key("semantic_scholar", SEMANTIC_SCHOLAR_SEARCH_URL, params)
    if is_cache_enabled():
        cached = get_cached("semantic_scholar", cache_key)
        if cached is not None:
            return _parse_s2_papers(cached), True

    url = f"{SEMANTIC_SCHOLAR_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers=_s2_headers())
    payload = None
    last_error: SemanticScholarError | None = None

    for attempt in range(SEMANTIC_SCHOLAR_MAX_RETRIES + 1):
        try:
            _wait_for_s2_rate_limit()
            with urllib.request.urlopen(request, timeout=SEMANTIC_SCHOLAR_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode())
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
                if SEMANTIC_SCHOLAR_API_KEY:
                    wait = SEMANTIC_SCHOLAR_MIN_INTERVAL
                else:
                    wait = min(SEMANTIC_SCHOLAR_INITIAL_BACKOFF * (2**attempt), 60.0)
                    wait *= random.uniform(1.0, 1.5)
                time.sleep(wait)
                continue
            raise last_error from exc
        except urllib.error.URLError as exc:
            raise SemanticScholarError(f"Request failed: {exc.reason}") from exc

    if payload is None:
        raise last_error or SemanticScholarError("Request failed")

    if is_cache_enabled():
        set_cached("semantic_scholar", cache_key, payload)
    return _parse_s2_papers(payload), False


def fetch_semantic_scholar_soft(
    query: str,
    limit: int = 100,
    offset: int = 0,
    *,
    year: str | None = None,
    fields_of_study: str | None = None,
) -> tuple[list[dict], str | None, bool]:
    try:
        papers, hit = search_semantic_scholar(
            query, limit=limit, offset=offset, year=year, fields_of_study=fields_of_study
        )
        return papers, None, hit
    except (SemanticScholarError, ValueError) as exc:
        return [], str(exc), False
