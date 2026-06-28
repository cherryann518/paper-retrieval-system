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

from src.cache import get_cached, is_cache_enabled, make_cache_key, set_cached

ARXIV_API_URL = "http://export.arxiv.org/api/query"
ARXIV_TIMEOUT = 30
ARXIV_MIN_INTERVAL = 3.0
ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

_last_arxiv_request_at = 0.0


class ArxivError(Exception):
    """Raised when an arXiv API request fails."""


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
        title = " ".join(
            (entry.findtext("atom:title", default="", namespaces=ARXIV_NS) or "").split()
        )
        summary = " ".join(
            (entry.findtext("atom:summary", default="", namespaces=ARXIV_NS) or "").split()
        )
        published = entry.findtext("atom:published", default="", namespaces=ARXIV_NS) or ""
        year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else None
        authors = [
            (a.findtext("atom:name", default="", namespaces=ARXIV_NS) or "").strip()
            for a in entry.findall("atom:author", ARXIV_NS)
        ]
        authors = [n for n in authors if n]
        primary = entry.find("arxiv:primary_category", ARXIV_NS)
        category = primary.get("term") if primary is not None else None
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
                "primary_category": category,
                "pdf_url": pdf_url,
            }
        )
    return papers


def search_arxiv(
    query: str, start: int = 0, max_results: int = 100
) -> tuple[list[dict], bool]:
    search_query = f"all:{query.strip()}"
    params: dict[str, Any] = {
        "search_query": search_query,
        "start": start,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    cache_key = make_cache_key("arxiv", ARXIV_API_URL, params)
    if is_cache_enabled():
        cached = get_cached("arxiv", cache_key)
        if cached is not None and "xml" in cached:
            return _parse_arxiv_xml(cached["xml"]), True

    url = f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "PaperRetrievalSystem/1.0"})
    try:
        _wait_for_arxiv_rate_limit()
        with urllib.request.urlopen(request, timeout=ARXIV_TIMEOUT) as resp:
            xml_text = resp.read().decode()
        _last_arxiv_request_at = time.monotonic()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise ArxivError(f"HTTP {exc.code}: {body or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ArxivError(f"Request failed: {exc.reason}") from exc

    if is_cache_enabled():
        set_cached("arxiv", cache_key, {"xml": xml_text})
    return _parse_arxiv_xml(xml_text), False


def fetch_arxiv_soft(
    query: str, start: int = 0, max_results: int = 100
) -> tuple[list[dict], str | None, bool]:
    try:
        papers, hit = search_arxiv(query, start=start, max_results=max_results)
        return papers, None, hit
    except (ArxivError, ValueError) as exc:
        return [], str(exc), False
