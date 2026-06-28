"""Tests for identifier-based dedupe and merge (E1–E3)."""

from src.identifiers import canonical_paper_id_from_dict
from src.schema import PaperRecord, paper_dedupe_key
from src.store import init_db, upsert_papers_batch


def test_dedupe_key_matches_paper_id_priority():
    paper = {
        "title": "Test",
        "externalIds": {"DOI": "10.1/x"},
        "s2_paper_id": "abc",
    }
    assert paper_dedupe_key(paper) == canonical_paper_id_from_dict(paper) == "doi:10.1/x"


def test_upsert_merges_by_doi_across_s2_ids(tmp_path):
    db_path = tmp_path / "papers.db"
    init_db(db_path)

    by_s2 = PaperRecord(
        paper_id="s2:aaa",
        title="Same Paper",
        doi="10.1/merge",
        s2_paper_id="aaa",
        sources=["semantic_scholar"],
        source_queries=["q1"],
    )
    by_doi = PaperRecord(
        paper_id="doi:10.1/merge",
        title="Same Paper Updated",
        doi="10.1/merge",
        arxiv_id="1234.5678",
        sources=["openalex"],
        source_queries=["q2"],
    )

    upsert_papers_batch([by_s2], db_path=db_path)
    stats = upsert_papers_batch([by_doi], db_path=db_path)

    assert stats["merged_by_identifier"] >= 1
    assert stats["updated"] == 1

    from src.store import get_all_papers

    papers = get_all_papers(db_path=db_path)
    assert len(papers) == 1
    assert sorted(papers[0].sources) == ["openalex", "semantic_scholar"]
    assert papers[0].arxiv_id == "1234.5678"
