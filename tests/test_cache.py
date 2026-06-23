"""Tests for source cache."""

import json
from pathlib import Path

from src.cache import get_cached, make_cache_key, set_cached


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("src.cache.CACHE_DIR", tmp_path)
    key = make_cache_key("semantic_scholar", "http://example.com", {"q": "test"})
    payload = {"data": []}
    assert get_cached("semantic_scholar", key) is None
    set_cached("semantic_scholar", key, payload)
    cached = get_cached("semantic_scholar", key)
    assert cached == payload
    path = tmp_path / "semantic_scholar" / f"{key}.json"
    assert path.exists()
    assert json.loads(path.read_text()) == payload
