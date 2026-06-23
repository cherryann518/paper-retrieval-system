"""
arXiv source adapter.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from src.cache import get_cached, make_cache_key, set_cached

ARXIV_API_URL = "http://export.arxiv.org/api/query"
ARXIV_TIMEOUT = 30
ARXIV_MIN_INTERVAL = 3.0
ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

_last_arxiv_request_at = 0.0
_use_cache = True


class ArxivError(Exception):
    """Raised when an arXiv API request fails."""


def set_cache_enabled(enabled: bool) -> None:
    global _use_cache
    _use_cache = enabled


def _wait_for_arxiv_rate_limit() -> None:
    global _last_arxiv_request_at
    elapsed = time.monotonic() - _last_arxiv_request_at
    if elapsed < ARXIV_MIN_INTERVAL:
        time.sleep(ARXIV_MIN_INTERVAL - elapsed)


def _arxiv_id_from_entry_id(entry_id: str) -> str:
    match = re.search(r"arxiv\.org/abs/(.+)$", entry_id)
    return match.group(1) if match else entry_id


def _parse_arxiv_xml(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    papers: list[dict] = []
    for entry in root.findall("atom:entry", ARXIV_NS):
        entry_id = (entry.findtext("atom:id", default="", namespaces=ARXIV_NS) or "").strip()
        title = (entry.findtext("atom:title", default="", namespaces=ARXIV_NS) or "").strip()
        title = " ".join(title.split())
        summary = (entry.findtext("atom:summary", default="", namespaces=ARXIV_NS) or "").strip()
        summary = " ".join(summary.split())
        published = (entry.findtext("atom:published", default="", namespaces=ARXIV_NS) or "").strip()
        year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else None
        authors = [
            (author.findtext("atom:name", default="", namespaces=ARXIV_NS) or "").strip()
            for author in entry.findall("atom:author", ARXIV_NS)
        ]
        authors = [name for name in authors if name]
        primary_cat = entry.find("arxiv:primary_category", ARXIV_NS)
        category = primary_cat.get("term") if primary_cat is not None else None
        pdf_url = None
        for link in entry.findall("atom:link", ARXIV_NS):
            if link.get("type") == "application/pdf":
                pdf_url = link.get("href")
                break
        arxiv_id = _arxiv_id_from_entry_id(entry_id)
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": authors,
                "year": year,
                "abstract": summary,
                "published": published,
                "primary_category": category,
                "pdf_url": pdf_url,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
            }
        )
    return papers


def search_arxiv(
    query: str,
    start: int = 0,
    max_results: int = 10,
    *,
    sort_by: str = "relevance",
    sort_order: str = "descending",
) -> tuple[list[dict], bool]:
    """
    Search arXiv for papers matching *query*.

    Returns (papers, cache_hit).
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    if start < 0:
        raise ValueError("start must be non-negative")
    if max_results < 1:
        raise ValueError("max_results must be at least 1")

    search_query = f"all:{query.strip()}"
    params: dict[str, Any] = {
        "search_query": search_query,
        "start": start,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": sort_order,
    }

    cache_key = make_cache_key("arxiv", ARXIV_API_URL, params)
    if _use_cache:
        cached = get_cached("arxiv", cache_key)
        if cached is not None and "xml" in cached:
            return _parse_arxiv_xml(cached["xml"]), True

    encoded = urllib.parse.urlencode(params)
    url = f"{ARXIV_API_URL}?{encoded}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "PaperRetrievalSystem/1.0"},
    )

    try:
        _wait_for_arxiv_rate_limit()
        with urllib.request.urlopen(request, timeout=ARXIV_TIMEOUT) as response:
            xml_text = response.read().decode()
        _last_arxiv_request_at = time.monotonic()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise ArxivError(f"HTTP {exc.code}: {body or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ArxivError(f"Request failed: {exc.reason}") from exc

    if _use_cache:
        set_cached("arxiv", cache_key, {"xml": xml_text})

    return _parse_arxiv_xml(xml_text), False


def fetch_arxiv_soft(
    query: str,
    start: int = 0,
    max_results: int = 10,
) -> tuple[list[dict], str | None, bool]:
    """Fail-soft arXiv fetch. Returns (papers, error, cache_hit)."""
    try:
        papers, cache_hit = search_arxiv(query, start=start, max_results=max_results)
        return papers, None, cache_hit
    except (ArxivError, ValueError) as exc:
        return [], str(exc), False
