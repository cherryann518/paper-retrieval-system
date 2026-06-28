"""Tests for query_state (G1/G2)."""

from src.loop_control import get_query_state, record_query_outcome
from src.store import init_db


def test_query_state_tracks_consecutive_zero_accept(tmp_path):
    db_path = tmp_path / "papers.db"
    init_db(db_path)

    record_query_outcome(
        "test query",
        accepted_count=0,
        rejected_count=5,
        error_count=0,
        db_path=db_path,
    )
    state = get_query_state("test query", db_path=db_path)
    assert state is not None
    assert state["consecutive_zero_accept"] == 1
    assert state["rejected_count"] == 5

    record_query_outcome(
        "test query",
        accepted_count=3,
        rejected_count=1,
        error_count=0,
        db_path=db_path,
    )
    state = get_query_state("test query", db_path=db_path)
    assert state["consecutive_zero_accept"] == 0
    assert state["accepted_count"] == 3
