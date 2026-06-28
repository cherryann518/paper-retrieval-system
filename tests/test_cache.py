"""Tests for sharded SQLite source cache."""

import json
import sqlite3

from src.cache import (
    CACHE_SHARDS_PER_SOURCE,
    get_cached,
    make_cache_key,
    set_cached,
    shard_db_path,
    shard_id,
)


def test_cache_roundtrip_sqlite_shard(tmp_path, monkeypatch):
    monkeypatch.setattr("src.cache.CACHE_DIR", tmp_path)
    key = make_cache_key("semantic_scholar", "http://example.com", {"q": "test"})
    payload = {"data": []}
    assert get_cached("semantic_scholar", key) is None
    set_cached("semantic_scholar", key, payload)
    assert get_cached("semantic_scholar", key) == payload

    db_path = shard_db_path("semantic_scholar", key)
    assert db_path.exists()
    assert db_path.name.startswith("shard_")
    assert db_path.suffix == ".sqlite"

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM api_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
    assert json.loads(row[0]) == payload


def test_shard_id_in_range():
    key = make_cache_key("arxiv", "http://example.com", {"q": "x"})
    sid = shard_id(key)
    assert 0 <= sid < CACHE_SHARDS_PER_SOURCE


def test_legacy_json_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("src.cache.CACHE_DIR", tmp_path)
    key = make_cache_key("arxiv", "http://example.com", {"q": "legacy"})
    payload = {"xml": "<feed/>"}
    legacy_dir = tmp_path / "arxiv"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")
    assert get_cached("arxiv", key) == payload
