"""
Score divergence helpers — SBERT vs lexical diagnostics.
"""

from __future__ import annotations

from typing import Any


def score_divergence_summary(papers: list[dict[str, Any]], *, top_n: int = 5) -> dict[str, Any]:
    """
    Summarize |sbert_cosine - lexical_v1| across ranked papers.

    Large deltas flag papers where semantic and keyword scores disagree.
    """
    if not papers:
        return {"count": 0, "avg_abs_delta": 0.0, "top_divergent": []}

    rows: list[dict[str, Any]] = []
    for paper in papers:
        scores = paper.get("scores") or {}
        sbert = float(scores.get("sbert_cosine", 0.0))
        lexical = float(scores.get("lexical_v1", paper.get("lexical_score", 0.0)))
        delta = round(sbert - lexical, 4)
        rows.append(
            {
                "title": paper.get("title") or "Untitled",
                "sbert_cosine": round(sbert, 4),
                "lexical_v1": round(lexical, 4),
                "delta": delta,
                "abs_delta": round(abs(delta), 4),
            }
        )

    avg_abs = sum(r["abs_delta"] for r in rows) / len(rows)
    top_divergent = sorted(rows, key=lambda r: r["abs_delta"], reverse=True)[:top_n]
    return {
        "count": len(rows),
        "avg_abs_delta": round(avg_abs, 4),
        "top_divergent": top_divergent,
    }
