"""
OpenAlex source adapter.

No API key required. Optional OPENALEX_MAILTO in .env for polite-pool rate limits.
Docs: https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from src.cache import get_cached, is_cache_enabled, make_cache_key, set_cached
from src.config import OPENALEX_BASE_URL, OPENALEX_MAILTO, OPENALEX_MAX_PER_PAGE, OPENALEX_MIN_INTERVAL

OPENALEX_WORKS_URL = f"{OPENALEX_BASE_URL.rstrip('/')}/works"
OPENALEX_TIMEOUT = 30
OPENALEX_FIELDS = (
    "id,doi,title,publication_year,cited_by_count,type,authorships,"
    "abstract_inverted_index,primary_location,ids"
)

_last_openalex_request_at = 0.0


class OpenAlexError(Exception):
    """Raised when an OpenAlex API request fails."""


def _wait_for_openalex_rate_limit() -> None:
    global _last_openalex_request_at
    interval = OPENALEX_MIN_INTERVAL if OPENALEX_MAILTO else 1.0
    elapsed = time.monotonic() - _last_openalex_request_at
    if elapsed < interval:
        time.sleep(interval - elapsed)


def _openalex_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "PaperRetrievalSystem/1.0 (mailto:openalex@example.com)",
    }
    if OPENALEX_MAILTO:
        headers["User-Agent"] = f"PaperRetrievalSystem/1.0 (mailto:{OPENALEX_MAILTO})"
    return headers


def _abstract_from_inverted_index(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    try:
        max_pos = max(max(positions) for positions in index.values())
    except ValueError:
        return None
    tokens = [""] * (max_pos + 1)
    for word, positions in index.items():
        for pos in positions:
            if 0 <= pos < len(tokens):
                tokens[pos] = word
    text = " ".join(t for t in tokens if t).strip()
    return text or None


def _parse_openalex_works(payload: dict[str, Any]) -> list[dict]:
    papers: list[dict] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        if not title:
            continue
        ids = item.get("ids") or {}
        authorships = item.get("authorships") or []
        authors = [
            (a.get("author") or {}).get("display_name", "").strip()
            for a in authorships
            if isinstance(a, dict)
        ]
        authors = [name for name in authors if name]
        primary = item.get("primary_location") or {}
        source = (primary.get("source") or {}).get("display_name") if isinstance(primary, dict) else None
        pdf_url = primary.get("pdf_url") if isinstance(primary, dict) else None
        papers.append(
            {
                "openalex_id": item.get("id") or ids.get("openalex"),
                "doi": item.get("doi") or ids.get("doi"),
                "title": title,
                "authors": authors,
                "year": item.get("publication_year"),
                "abstract": _abstract_from_inverted_index(item.get("abstract_inverted_index")),
                "cited_by_count": item.get("cited_by_count"),
                "venue": source,
                "pdf_url": pdf_url,
                "work_type": item.get("type"),
                "ids": ids,
            }
        )
    return papers


def search_openalex(
    query: str,
    *,
    per_page: int = OPENALEX_MAX_PER_PAGE,
    cursor: str | None = None,
    publication_year: int | None = None,
) -> tuple[list[dict], bool, str | None]:
    """
    Search OpenAlex works.

    Returns (papers, cache_hit, next_cursor).
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")

    params: dict[str, Any] = {
        "search": query.strip(),
        "per_page": min(max(per_page, 1), OPENALEX_MAX_PER_PAGE),
        "select": OPENALEX_FIELDS,
    }
    if cursor:
        params["cursor"] = cursor
    else:
        params["cursor"] = "*"
    if publication_year is not None:
        params["filter"] = f"publication_year:{publication_year}"
    if OPENALEX_MAILTO:
        params["mailto"] = OPENALEX_MAILTO

    cache_key = make_cache_key("openalex", OPENALEX_WORKS_URL, params)
    if is_cache_enabled():
        cached = get_cached("openalex", cache_key)
        if cached is not None:
            meta = cached.get("meta") or {}
            return (
                _parse_openalex_works(cached),
                True,
                meta.get("next_cursor"),
            )

    url = f"{OPENALEX_WORKS_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers=_openalex_headers())
    try:
        _wait_for_openalex_rate_limit()
        with urllib.request.urlopen(request, timeout=OPENALEX_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode())
        global _last_openalex_request_at
        _last_openalex_request_at = time.monotonic()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise OpenAlexError(f"HTTP {exc.code}: {body or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise OpenAlexError(f"Request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAlexError("Invalid JSON from OpenAlex") from exc

    if is_cache_enabled():
        set_cached("openalex", cache_key, payload)

    meta = payload.get("meta") or {}
    return _parse_openalex_works(payload), False, meta.get("next_cursor")


def fetch_openalex_soft(
    query: str,
    *,
    per_page: int = OPENALEX_MAX_PER_PAGE,
    cursor: str | None = None,
    publication_year: int | None = None,
) -> tuple[list[dict], str | None, bool, str | None]:
    """Fail-soft fetch. Returns (papers, error, cache_hit, next_cursor)."""
    try:
        papers, hit, next_cursor = search_openalex(
            query,
            per_page=per_page,
            cursor=cursor,
            publication_year=publication_year,
        )
        return papers, None, hit, next_cursor
    except (OpenAlexError, ValueError) as exc:
        return [], str(exc), False, None
