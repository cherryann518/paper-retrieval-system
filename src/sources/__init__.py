"""Source adapters for external paper APIs."""

from src.sources.arxiv import ArxivError, fetch_arxiv_soft, search_arxiv
from src.sources.openalex import OpenAlexError, fetch_openalex_soft, search_openalex
from src.sources.semantic_scholar import (
    SemanticScholarError,
    fetch_semantic_scholar_soft,
    search_semantic_scholar,
)

__all__ = [
    "ArxivError",
    "OpenAlexError",
    "SemanticScholarError",
    "fetch_arxiv_soft",
    "fetch_openalex_soft",
    "fetch_semantic_scholar_soft",
    "search_arxiv",
    "search_openalex",
    "search_semantic_scholar",
]
