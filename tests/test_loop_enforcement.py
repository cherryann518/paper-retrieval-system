"""Tests for dead-query loop enforcement (G3)."""

from src.loop_control import filter_dead_queries, record_query_outcome
from src.store import init_db


def test_filter_dead_queries_skips_in_survey_mode(tmp_path):
    db_path = tmp_path / "papers.db"
    init_db(db_path)

    for _ in range(3):
        record_query_outcome(
            "stale query",
            accepted_count=0,
            rejected_count=1,
            error_count=0,
            db_path=db_path,
        )

    active, skipped = filter_dead_queries(
        ["user query", "stale query", "fresh query"],
        threshold=3,
        survey_mode=True,
        db_path=db_path,
    )
    assert "stale query" not in active
    assert any(s["query"] == "stale query" for s in skipped)
    assert "user query" in active


def test_filter_dead_queries_never_empty(tmp_path):
    db_path = tmp_path / "papers.db"
    init_db(db_path)

    for _ in range(3):
        record_query_outcome(
            "only query",
            accepted_count=0,
            rejected_count=1,
            error_count=0,
            db_path=db_path,
        )

    active, skipped = filter_dead_queries(
        ["only query"],
        threshold=3,
        survey_mode=True,
        db_path=db_path,
    )
    assert active == ["only query"]
    assert skipped == []


def test_filter_dead_queries_disabled_outside_survey(tmp_path):
    db_path = tmp_path / "papers.db"
    init_db(db_path)
    record_query_outcome(
        "dead",
        accepted_count=0,
        rejected_count=1,
        error_count=0,
        db_path=db_path,
    )

    active, skipped = filter_dead_queries(
        ["dead"],
        threshold=1,
        survey_mode=False,
        db_path=db_path,
    )
    assert active == ["dead"]
    assert skipped == []
