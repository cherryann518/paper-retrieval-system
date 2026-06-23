"""Tests for main paper store."""

from pathlib import Path

from src.schema import PaperRecord
from src.store import get_all_papers, init_db, upsert_papers_batch


def test_upsert_and_merge(tmp_path):
    db_path = tmp_path / "papers.db"
    init_db(db_path)
    record = PaperRecord(
        paper_id="doi:10.1/test",
        title="Test Paper",
        authors=["Alice"],
        year=2024,
        abstract="An abstract.",
        doi="10.1/test",
        sources=["semantic_scholar"],
        source_queries=["query one"],
    )
    stats = upsert_papers_batch([record], db_path=db_path)
    assert stats["inserted"] == 1

    updated = PaperRecord(
        paper_id="doi:10.1/test",
        title="Test Paper",
        authors=["Alice", "Bob"],
        year=2024,
        abstract="An abstract.",
        doi="10.1/test",
        sources=["arxiv"],
        source_queries=["query two"],
    )
    stats2 = upsert_papers_batch([updated], db_path=db_path)
    assert stats2["updated"] == 1

    papers = get_all_papers(db_path=db_path)
    assert len(papers) == 1
    assert sorted(papers[0].sources) == ["arxiv", "semantic_scholar"]
    assert papers[0].authors == ["Alice", "Bob"]
