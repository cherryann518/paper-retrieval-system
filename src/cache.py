"""
Per-source raw API response cache — 3 SQLite shard DBs per source.

Each lookup opens one shard. Payloads are raw API JSON/XML (pre-normalize).
Entries expire after cache_ttl_days (lazy delete on read).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.config import CACHE_DIR, CACHE_SHARDS_PER_SOURCE, DEFAULT_CACHE_TTL_DAYS

_use_cache = True
_cache_ttl_days: float = DEFAULT_CACHE_TTL_DAYS


def set_cache_enabled(enabled: bool) -> None:
    global _use_cache
    _use_cache = enabled


def is_cache_enabled() -> bool:
    return _use_cache


def set_cache_ttl_days(days: float) -> None:
    """0 = never expire."""
    global _cache_ttl_days
    _cache_ttl_days = max(0.0, float(days))


def get_cache_ttl_days() -> float:
    return _cache_ttl_days


def make_cache_key(source: str, url: str, params: dict[str, Any]) -> str:
    payload = json.dumps(
        {"source": source, "url": url, "params": sorted(params.items())},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def shard_id(cache_key: str, *, shard_count: int = CACHE_SHARDS_PER_SOURCE) -> int:
    return int(cache_key[:16], 16) % shard_count


def shard_db_path(source: str, cache_key: str) -> Path:
    sid = shard_id(cache_key)
    return CACHE_DIR / source / f"shard_{sid}.sqlite"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().replace(microsecond=0).isoformat()


def _parse_created_at(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _is_expired(created_at: str) -> bool:
    if _cache_ttl_days <= 0:
        return False
    parsed = _parse_created_at(created_at)
    if parsed is None:
        return True
    age = _utc_now() - parsed
    return age > timedelta(days=_cache_ttl_days)


def _init_shard(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS api_cache (
            cache_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_api_cache_created ON api_cache(created_at);
        """
    )


def _legacy_json_path(source: str, cache_key: str) -> Path:
    return CACHE_DIR / source / f"{cache_key}.json"


def _delete_cache_row(db_path: Path, cache_key: str) -> None:
    if not db_path.exists():
        return
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM api_cache WHERE cache_key = ?", (cache_key,))
            conn.commit()
    except sqlite3.Error:
        pass


def get_cached(source: str, cache_key: str) -> dict[str, Any] | None:
    db_path = shard_db_path(source, cache_key)
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                _init_shard(conn)
                row = conn.execute(
                    "SELECT payload_json, created_at FROM api_cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
            if row is not None:
                if _is_expired(row[1]):
                    _delete_cache_row(db_path, cache_key)
                else:
                    return json.loads(row[0])
        except (json.JSONDecodeError, OSError, sqlite3.Error):
            pass

    legacy = _legacy_json_path(source, cache_key)
    if legacy.exists():
        try:
            return json.loads(legacy.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def set_cached(source: str, cache_key: str, raw_payload: dict[str, Any]) -> None:
    db_path = shard_db_path(source, cache_key)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    payload_json = json.dumps(raw_payload, ensure_ascii=False)
    now = _utc_now_iso()
    with sqlite3.connect(db_path) as conn:
        _init_shard(conn)
        conn.execute(
            """
            INSERT INTO api_cache (cache_key, payload_json, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload_json = excluded.payload_json,
                created_at = excluded.created_at
            """,
            (cache_key, payload_json, now),
        )
        conn.commit()


def purge_expired_cache(*, source: str | None = None) -> int:
    """Delete expired rows across shards. Returns rows removed."""
    if _cache_ttl_days <= 0:
        return 0
    removed = 0
    sources = [source] if source else [
        d.name for d in CACHE_DIR.iterdir() if d.is_dir()
    ] if CACHE_DIR.exists() else []
    for src in sources:
        for shard_path in list_cache_shards(src):
            if not shard_path.exists():
                continue
            try:
                with sqlite3.connect(shard_path) as conn:
                    _init_shard(conn)
                    rows = conn.execute(
                        "SELECT cache_key, created_at FROM api_cache"
                    ).fetchall()
                    for cache_key, created_at in rows:
                        if _is_expired(created_at):
                            conn.execute(
                                "DELETE FROM api_cache WHERE cache_key = ?",
                                (cache_key,),
                            )
                            removed += 1
                    conn.commit()
            except sqlite3.Error:
                continue
    return removed


def list_cache_shards(source: str) -> list[Path]:
    return [
        CACHE_DIR / source / f"shard_{i}.sqlite"
        for i in range(CACHE_SHARDS_PER_SOURCE)
    ]
