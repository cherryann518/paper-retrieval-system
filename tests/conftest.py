"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from src.schema import PaperRecord


@pytest.fixture
def sample_paper_dicts() -> list[dict]:
    return [
        {
            "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
            "authors": ["Patrick Lewis"],
            "year": 2020,
            "abstract": "retrieval augmented generation language models knowledge",
            "externalIds": {"DOI": "10.5555/123", "arXiv": "2005.11401"},
        },
        {
            "title": "Unrelated Coral Bleaching Ecology Study",
            "authors": ["Jane Doe"],
            "year": 2019,
            "abstract": "coral reefs ocean temperature marine biology",
            "externalIds": {"DOI": "10.5555/999"},
        },
        {
            "title": "Recent Transformer Survey",
            "authors": ["Bob Smith"],
            "year": 2025,
            "abstract": "survey of neural network architectures",
            "externalIds": {},
        },
    ]


@pytest.fixture
def sample_records() -> list[PaperRecord]:
    return [
        PaperRecord(
            paper_id="doi:10.5555/123",
            title="Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
            authors=["Patrick Lewis"],
            year=2020,
            abstract="retrieval augmented generation",
            doi="10.5555/123",
            arxiv_id="2005.11401",
            sources=["semantic_scholar"],
            source_queries=["rag"],
        ),
        PaperRecord(
            paper_id="arxiv:1706.03762",
            title="Attention Is All You Need",
            authors=["Ashish Vaswani"],
            year=2017,
            abstract="transformer attention",
            arxiv_id="1706.03762",
            sources=["arxiv"],
            source_queries=["rag"],
        ),
    ]
