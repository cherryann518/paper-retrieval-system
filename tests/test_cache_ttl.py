"""Tests for cache TTL."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from src.cache import get_cached, make_cache_key, set_cache_ttl_days, set_cached, shard_db_path


def test_cache_expires_after_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr("src.cache.CACHE_DIR", tmp_path)
    set_cache_ttl_days(7)
    key = make_cache_key("semantic_scholar", "http://example.com", {"q": "ttl"})
    payload = {"data": []}
    set_cached("semantic_scholar", key, payload)

    db_path = shard_db_path("semantic_scholar", key)
    old = (datetime.now(timezone.utc) - timedelta(days=8)).replace(microsecond=0).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE api_cache SET created_at = ? WHERE cache_key = ?", (old, key))
        conn.commit()

    assert get_cached("semantic_scholar", key) is None


def test_cache_ttl_zero_never_expires(tmp_path, monkeypatch):
    monkeypatch.setattr("src.cache.CACHE_DIR", tmp_path)
    set_cache_ttl_days(0)
    key = make_cache_key("openalex", "http://example.com", {"q": "forever"})
    payload = {"results": []}
    set_cached("openalex", key, payload)

    db_path = shard_db_path("openalex", key)
    old = (datetime.now(timezone.utc) - timedelta(days=365)).replace(microsecond=0).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE api_cache SET created_at = ? WHERE cache_key = ?", (old, key))
        conn.commit()

    assert get_cached("openalex", key) == payload
