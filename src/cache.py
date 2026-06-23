"""
Per-source API response cache.

Stores raw payloads under outputs/cache/{source}/{hash}.json
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.config import CACHE_DIR


def make_cache_key(source: str, url: str, params: dict[str, Any]) -> str:
    """Deterministic cache key from source, URL, and sorted params."""
    payload = json.dumps(
        {"source": source, "url": url, "params": sorted(params.items())},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _cache_path(source: str, cache_key: str) -> Path:
    return CACHE_DIR / source / f"{cache_key}.json"


def get_cached(source: str, cache_key: str) -> dict[str, Any] | None:
    path = _cache_path(source, cache_key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def set_cached(source: str, cache_key: str, raw_payload: dict[str, Any]) -> None:
    path = _cache_path(source, cache_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw_payload, ensure_ascii=False), encoding="utf-8")
