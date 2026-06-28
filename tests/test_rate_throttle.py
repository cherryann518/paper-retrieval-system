"""Tests for fetch rate-limit throttle (G5)."""

from src.fetch import FetchStats, fetch_all_sources, SurveyConfig
from src.rate_throttle import FetchThrottle, is_rate_limit_error


def test_is_rate_limit_error():
    assert is_rate_limit_error("HTTP 429 Too Many Requests")
    assert not is_rate_limit_error("HTTP 503")


def test_fetch_throttle_reduces_workers_after_threshold():
    throttle = FetchThrottle()
    assert throttle.effective_workers(3) == 3

    stats = FetchStats(
        fetch_errors=[
            {"error": "429"},
            {"error": "429"},
        ]
    )
    throttle.observe_errors(stats.fetch_errors, threshold=2)
    assert throttle.throttled
    assert throttle.effective_workers(3) == 1


def test_fetch_all_sources_accepts_throttle(monkeypatch):
    monkeypatch.setattr(
        "src.fetch.fetch_semantic_scholar_soft",
        lambda *a, **k: ([], "429", False),
    )
    monkeypatch.setattr("src.fetch.fetch_arxiv_soft", lambda *a, **k: ([], None, True))
    monkeypatch.setattr(
        "src.fetch.fetch_openalex_soft",
        lambda *a, **k: ([], None, True, None),
    )

    cfg = SurveyConfig(
        sources=["semantic_scholar", "arxiv", "openalex"],
        timeline_from_year=2020,
        timeline_to_year=2020,
        year_chunk_fetch=False,
        rate_limit_threshold=1,
    )
    throttle = FetchThrottle()
    _, stats = fetch_all_sources("test", cfg, throttle=throttle)
    assert stats.rate_limit_errors >= 1
    assert throttle.throttled
    assert throttle.effective_workers(3) == 1
