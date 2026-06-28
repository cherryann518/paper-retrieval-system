"""Tests for FTS5 cross-query corpus pre-fetch (G4)."""

from src.schema import PaperRecord
from src.store import init_db, search_corpus_fts, upsert_papers_batch


def test_search_corpus_fts_finds_cross_query_papers(tmp_path):
    db_path = tmp_path / "papers.db"
    init_db(db_path)

    record = PaperRecord(
        paper_id="doi:10.1/fts",
        title="Neural Retrieval Augmented Generation",
        abstract="Combining dense retrieval with language models for knowledge tasks.",
        year=2024,
        doi="10.1/fts",
        sources=["arxiv"],
        source_queries=["unrelated geology query"],
    )
    upsert_papers_batch([record], db_path=db_path)

    hits = search_corpus_fts("retrieval augmented generation", limit=10, db_path=db_path)
    assert len(hits) == 1
    assert hits[0]["paper_id"] == "doi:10.1/fts"


def test_search_corpus_fts_empty_for_short_query(tmp_path):
    db_path = tmp_path / "papers.db"
    init_db(db_path)
    assert search_corpus_fts("a an", db_path=db_path) == []
