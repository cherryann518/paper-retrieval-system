"""Runtime flags for retrieval pipeline."""

from __future__ import annotations

from src.sources import arxiv as arxiv_source
from src.sources import semantic_scholar as s2_source


def set_cache_enabled(enabled: bool) -> None:
    s2_source.set_cache_enabled(enabled)
    arxiv_source.set_cache_enabled(enabled)
