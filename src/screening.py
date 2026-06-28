"""
Staged screening: accept/reject ranked papers with auditable reasons.
"""

from __future__ import annotations

from typing import Any

from src.fetch import SurveyConfig


def apply_screening(
    ranked: list[dict[str, Any]],
    config: SurveyConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Filter ranked pool. Returns (accepted, rejects).

    Reject reasons: missing_title, below_min_score, outside_timeline.
    """
    accepted: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []

    for paper in ranked:
        title = (paper.get("title") or "").strip()
        if not title:
            rejects.append(_reject_record(paper, "missing_title", {}))
            continue

        score = float(paper.get("relevance_score") or 0.0)
        if score < config.min_relevance_score:
            rejects.append(
                _reject_record(
                    paper,
                    "below_min_score",
                    {"score": score, "threshold": config.min_relevance_score},
                )
            )
            continue

        year = paper.get("year")
        if config.strict_timeline_filter and isinstance(year, int):
            if year < config.timeline_from_year or year > config.timeline_to_year:
                rejects.append(
                    _reject_record(
                        paper,
                        "outside_timeline",
                        {
                            "year": year,
                            "from": config.timeline_from_year,
                            "to": config.timeline_to_year,
                        },
                    )
                )
                continue

        accepted.append(paper)

    return accepted, rejects


def _reject_record(paper: dict[str, Any], reason: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": paper.get("paper_id"),
        "title": paper.get("title"),
        "reason": reason,
        "evidence": evidence,
        "relevance_score": paper.get("relevance_score"),
        "year": paper.get("year"),
    }
