"""Tests for source adapters using fixtures (no network)."""

import json
from pathlib import Path

from src.cache import get_cached, make_cache_key, set_cached
from src.sources.arxiv import _parse_arxiv_xml
from src.sources.semantic_scholar import _parse_s2_papers

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_s2_papers_fixture():
    payload = json.loads((FIXTURES / "s2_sample.json").read_text())
    papers = _parse_s2_papers(payload)
    assert len(papers) == 1
    assert papers[0]["paperId"] == "abc123"
    assert papers[0]["externalIds"]["DOI"] == "10.5555/123"
    assert papers[0]["pdf_url"] == "https://example.com/paper.pdf"


def test_parse_arxiv_xml_fixture():
    xml_text = (FIXTURES / "arxiv_sample.xml").read_text()
    papers = _parse_arxiv_xml(xml_text)
    assert len(papers) == 1
    assert papers[0]["title"] == "Attention Is All You Need"
    assert papers[0]["pdf_url"].endswith("1706.03762v7")


def test_semantic_scholar_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("src.sources.semantic_scholar._use_cache", True)
    monkeypatch.setattr("src.cache.CACHE_DIR", tmp_path)

    payload = json.loads((FIXTURES / "s2_sample.json").read_text())
    params = {"query": "rag", "limit": 10, "offset": 0, "fields": "title"}
    key = make_cache_key("semantic_scholar", "https://api.example.com/search", params)
    set_cached("semantic_scholar", key, payload)

    assert get_cached("semantic_scholar", key) == payload
