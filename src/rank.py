"""
Multi-metric paper ranking (SBERT / TF-IDF / recency).
"""

from __future__ import annotations

from typing import Any, Literal

from src.config import EMBEDDING_MODEL_NAME
from src.lexical import rank_lexical

RankMethod = Literal["sbert", "tfidf", "recency"]

_embedding_model = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def _paper_text(paper: dict[str, Any]) -> str:
    return f"{paper.get('title') or ''} {paper.get('abstract') or ''}".strip()


def rank_sbert(query: str, papers: list[dict[str, Any]]) -> dict[int, float]:
    if not papers:
        return {}
    from sentence_transformers.util import cos_sim

    model = _get_embedding_model()
    query_embedding = model.encode(query.strip(), convert_to_tensor=True)
    paper_embeddings = model.encode(
        [_paper_text(p) for p in papers], convert_to_tensor=True
    )
    scores = cos_sim(query_embedding, paper_embeddings)[0].tolist()
    return {id(p): float(s) for p, s in zip(papers, scores)}


def rank_tfidf(query: str, papers: list[dict[str, Any]]) -> dict[int, float]:
    if not papers:
        return {}
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    texts = [_paper_text(p) for p in papers]
    matrix = TfidfVectorizer(stop_words="english").fit_transform([query.strip()] + texts)
    scores = cosine_similarity(matrix[0:1], matrix[1:])[0]
    return {id(p): float(s) for p, s in zip(papers, scores)}


def rank_recency(
    papers: list[dict[str, Any]], *, from_year: int, to_year: int
) -> dict[int, float]:
    if not papers:
        return {}
    span = max(to_year - from_year, 1)
    scores: dict[int, float] = {}
    for paper in papers:
        year = paper.get("year")
        if not isinstance(year, int) or year < from_year or year > to_year:
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
    from_year: int = 2020,
    to_year: int = 2026,
    include_lexical: bool = True,
) -> list[dict[str, Any]]:
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not papers:
        return []

    methods = methods or ["sbert", "tfidf", "recency"]
    method_scores: dict[str, dict[int, float]] = {}
    lexical_components: dict[int, dict[str, float]] = {}

    if "sbert" in methods:
        method_scores["sbert_cosine"] = rank_sbert(query, papers)
    if "tfidf" in methods:
        method_scores["tfidf_cosine"] = rank_tfidf(query, papers)
    if "recency" in methods:
        method_scores["recency"] = rank_recency(papers, from_year=from_year, to_year=to_year)
    if include_lexical:
        from src.lexical import score_lexical_v1

        method_scores["lexical_v1"] = rank_lexical(
            query, papers, from_year=from_year, to_year=to_year
        )
        for paper in papers:
            lexical_components[id(paper)] = score_lexical_v1(
                query, paper, from_year=from_year, to_year=to_year
            )

    primary_key = {
        "sbert": "sbert_cosine",
        "tfidf": "tfidf_cosine",
        "recency": "recency",
    }[primary_method]

    ranked: list[dict[str, Any]] = []
    for paper in papers:
        scores = {
            name: round(values.get(id(paper), 0.0), 4)
            for name, values in method_scores.items()
        }
        copy = dict(paper)
        copy["scores"] = scores
        if include_lexical and id(paper) in lexical_components:
            comp = lexical_components[id(paper)]
            copy["lexical_components"] = {
                k: v for k, v in comp.items() if k != "lexical_v1"
            }
        copy["rank_method"] = primary_key
        copy["relevance_score"] = scores.get(primary_key, 0.0)
        copy["lexical_score"] = scores.get("lexical_v1", 0.0)
        ranked.append(copy)
    return sorted(ranked, key=lambda p: p["relevance_score"], reverse=True)


def embed_and_rank(query: str, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return rank_papers(query, papers, methods=["sbert"], primary_method="sbert")
