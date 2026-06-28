"""Tests for fuzzy title duplicate flagging (E4)."""

from src.fuzzy_dedupe import normalize_fuzzy_title, years_compatible
from src.schema import PaperRecord
from src.store import init_db, upsert_papers_batch


def test_normalize_fuzzy_title_strips_subtitle():
    assert normalize_fuzzy_title("Attention Is All You Need: A Survey") == "attention is all you need"


def test_years_compatible_within_tolerance():
    assert years_compatible(2020, 2021)
    assert not years_compatible(2020, 2022)


def test_fuzzy_duplicate_flagged_not_merged(tmp_path):
    db_path = tmp_path / "papers.db"
    init_db(db_path)

    first = PaperRecord(
        paper_id="fp:aaa",
        title="Retrieval Augmented Generation Systems",
        year=2023,
        sources=["arxiv"],
        source_queries=["q1"],
    )
    second = PaperRecord(
        paper_id="fp:bbb",
        title="Retrieval Augmented Generation Systems: Extended",
        year=2023,
        doi=None,
        sources=["semantic_scholar"],
        source_queries=["q2"],
    )

    upsert_papers_batch([first], db_path=db_path)
    stats = upsert_papers_batch([second], db_path=db_path, fuzzy_dedupe_enabled=True)

    assert stats["possible_duplicates_flagged"] == 1

    from src.store import get_all_papers, _connect

    assert len(get_all_papers(db_path=db_path)) == 2
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM possible_duplicates").fetchone()
    assert row["n"] == 1
