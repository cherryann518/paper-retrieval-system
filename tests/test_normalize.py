"""Tests for normalization and schema."""

from pathlib import Path

from src.normalize import merge_paper_records, normalize_arxiv, normalize_s2
from src.schema import paper_id_from_ids
from src.sources.arxiv import _parse_arxiv_xml

FIXTURES = Path(__file__).parent / "fixtures"


def test_paper_id_priority():
    assert paper_id_from_ids(doi="10.1/abc") == "doi:10.1/abc"
    assert paper_id_from_ids(arxiv_id="1706.03762v1") == "arxiv:1706.03762"
    assert paper_id_from_ids(s2_paper_id="s2id") == "s2:s2id"
    assert paper_id_from_ids(title="Hello World", year=2020).startswith("fp:")


def test_normalize_s2_fixture():
    import json

    payload = json.loads((FIXTURES / "s2_sample.json").read_text())
    raw = payload["data"][0]
    record = normalize_s2(raw, source_query="rag")
    assert record is not None
    assert record.paper_id == "doi:10.5555/123"
    assert record.title.startswith("Retrieval-Augmented")
    assert record.sources == ["semantic_scholar"]
    assert record.source_queries == ["rag"]
    assert record.pdf_url == "https://example.com/paper.pdf"


def test_normalize_arxiv_fixture():
    xml_text = (FIXTURES / "arxiv_sample.xml").read_text()
    papers = _parse_arxiv_xml(xml_text)
    assert len(papers) == 1
    record = normalize_arxiv(papers[0], source_query="transformer")
    assert record is not None
    assert record.arxiv_id == "1706.03762"
    assert record.year == 2017
    assert record.sources == ["arxiv"]


def test_merge_paper_records_combines_sources():
    import json

    payload = json.loads((FIXTURES / "s2_sample.json").read_text())
    s2 = normalize_s2(payload["data"][0], source_query="q1")
    xml_text = (FIXTURES / "arxiv_sample.xml").read_text()
    arxiv = normalize_arxiv(_parse_arxiv_xml(xml_text)[0], source_query="q2")
    merged = merge_paper_records([s2, arxiv])
    assert len(merged) == 2
