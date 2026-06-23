"""
Multi-metric paper ranking.
"""

from __future__ import annotations

from typing import Any, Literal

from src.config import (
    SCORE_GOOD,
    SCORE_TOP_MIN,
    TIMELINE_FROM_YEAR,
    TIMELINE_TO_YEAR,
)

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
RankMethod = Literal["sbert", "tfidf", "recency"]

_embedding_model = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def _paper_text(paper: dict[str, Any]) -> str:
    title = paper.get("title") or ""
    abstract = paper.get("abstract") or ""
    return f"{title} {abstract}".strip()


def rank_sbert(query: str, papers: list[dict[str, Any]]) -> dict[str, float]:
    if not papers:
        return {}
    from sentence_transformers.util import cos_sim

    model = _get_embedding_model()
    query_embedding = model.encode(query.strip(), convert_to_tensor=True)
    paper_embeddings = model.encode(
        [_paper_text(paper) for paper in papers],
        convert_to_tensor=True,
    )
    scores = cos_sim(query_embedding, paper_embeddings)[0].tolist()
    return {id(paper): float(score) for paper, score in zip(papers, scores)}


def rank_tfidf(query: str, papers: list[dict[str, Any]]) -> dict[str, float]:
    if not papers:
        return {}
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    texts = [_paper_text(paper) for paper in papers]
    vectorizer = TfidfVectorizer(stop_words="english")
    matrix = vectorizer.fit_transform([query.strip()] + texts)
    query_vec = matrix[0:1]
    doc_vecs = matrix[1:]
    scores = cosine_similarity(query_vec, doc_vecs)[0]
    return {id(paper): float(score) for paper, score in zip(papers, scores)}


def rank_recency(
    papers: list[dict[str, Any]],
    *,
    from_year: int = TIMELINE_FROM_YEAR,
    to_year: int = TIMELINE_TO_YEAR,
) -> dict[str, float]:
    if not papers:
        return {}
    span = max(to_year - from_year, 1)
    scores: dict[str, float] = {}
    for paper in papers:
        year = paper.get("year")
        if not isinstance(year, int):
            scores[id(paper)] = 0.0
            continue
        if year < from_year or year > to_year:
            scores[id(paper)] = 0.0
        else:
            scores[id(paper)] = (year - from_year) / span
    return scores


def rank_papers(
    query: str,
    papers: list[dict[str, Any]],
    *,
    methods: list[RankMethod] | None = None,
    primary_method: RankMethod = "sbert",
    from_year: int = TIMELINE_FROM_YEAR,
    to_year: int = TIMELINE_TO_YEAR,
) -> list[dict[str, Any]]:
    """
    Score papers with multiple metrics; sort by primary_method score.

    Each paper gets scores dict and relevance_score from primary method.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not papers:
        return []

    methods = methods or ["sbert", "tfidf", "recency"]
    method_scores: dict[str, dict[str, float]] = {}

    if "sbert" in methods:
        method_scores["sbert_cosine"] = rank_sbert(query, papers)
    if "tfidf" in methods:
        method_scores["tfidf_cosine"] = rank_tfidf(query, papers)
    if "recency" in methods:
        method_scores["recency"] = rank_recency(
            papers, from_year=from_year, to_year=to_year
        )

    primary_key = {
        "sbert": "sbert_cosine",
        "tfidf": "tfidf_cosine",
        "recency": "recency",
    }[primary_method]

    ranked: list[dict[str, Any]] = []
    for paper in papers:
        paper_key = id(paper)
        scores = {
            name: round(values.get(paper_key, 0.0), 4)
            for name, values in method_scores.items()
        }
        paper_copy = dict(paper)
        paper_copy["scores"] = scores
        paper_copy["rank_method"] = primary_key
        paper_copy["relevance_score"] = scores.get(primary_key, 0.0)
        ranked.append(paper_copy)

    return sorted(ranked, key=lambda p: p["relevance_score"], reverse=True)


def embed_and_rank(query: str, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Backward-compatible SBERT-only ranking."""
    return rank_papers(query, papers, methods=["sbert"], primary_method="sbert")
