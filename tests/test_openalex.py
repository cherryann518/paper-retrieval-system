"""Tests for OpenAlex normalization."""

import json
from pathlib import Path

from src.normalize import normalize_openalex
from src.sources.openalex import _parse_openalex_works

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_openalex_fixture():
    payload = json.loads((FIXTURES / "openalex_sample.json").read_text())
    papers = _parse_openalex_works(payload)
    assert len(papers) == 1
    assert papers[0]["title"].startswith("Retrieval-Augmented")
    assert papers[0]["abstract"] == "Large language models with retrieval"


def test_normalize_openalex_fixture():
    payload = json.loads((FIXTURES / "openalex_sample.json").read_text())
    raw = _parse_openalex_works(payload)[0]
    record = normalize_openalex(raw, source_query="rag")
    assert record is not None
    assert record.paper_id == "doi:10.5555/1234567"
    assert record.openalex_id == "W2741809807"
    assert record.arxiv_id == "2005.11401"
    assert record.sources == ["openalex"]
