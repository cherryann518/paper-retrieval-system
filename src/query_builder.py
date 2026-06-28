"""
Deterministic canonical query list from survey config (no LLM).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.fetch import SurveyConfig

_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "on", "for", "to", "with",
        "is", "are", "was", "were", "be", "by", "from", "as", "at", "how",
        "what", "why", "when", "does", "do", "can", "that", "this",
    }
)


def _clean_query(text: str) -> str:
    return " ".join(text.strip().split())


def _dedupe_queries(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        cleaned = _clean_query(q)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(cleaned)
    return unique


def _combined_query_from_topic(topic: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", topic.lower())
    ranked = sorted(
        {t for t in tokens if t not in _STOPWORDS and len(t) > 2},
        key=lambda t: (-len(t), t),
    )
    return " ".join(ranked[:8]) if ranked else _clean_query(topic)


def build_canonical_queries(
    config: SurveyConfig,
    *,
    user_query: str | None = None,
    include_config_queries: bool = False,
) -> list[str]:
    """
    Build ordered query list for a retrieval run.

    Single search (UI/CLI default): user_query only.
    Survey mode: user_query + topic + research_questions + hints + combined.
    """
    queries: list[str] = []

    if user_query and user_query.strip():
        queries.append(_clean_query(user_query))

    if not include_config_queries:
        return _dedupe_queries(queries)

    topic = _clean_query(config.topic_overview)
    if topic and topic.lower() not in {q.lower() for q in queries}:
        queries.append(topic)

    for rq in config.research_questions:
        queries.append(_clean_query(rq))

    for hint in config.query_hints:
        queries.append(_clean_query(hint))

    combined = _combined_query_from_topic(config.topic_overview)
    if combined:
        queries.append(combined)

    queries = _dedupe_queries(queries)
    if config.max_queries and len(queries) > config.max_queries:
        queries = queries[: config.max_queries]
    return queries
