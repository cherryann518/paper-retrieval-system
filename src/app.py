"""
Flask web server for the paper retrieval pipeline.

Serves a minimal frontend and exposes POST /search for ranked paper results.
"""

import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from src.agent import run_search_agent
from src.tools import SemanticScholarError, embed_and_rank, load_sample_papers

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR))


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.post("/search")
def search():
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()
    offline = bool(body.get("offline", False))

    if not query:
        return jsonify({"error": "query is required"}), 400

    started = time.perf_counter()
    source = "offline" if offline else "live"
    print(f"[search] query={query!r} source={source}", flush=True)

    try:
        if offline:
            papers = load_sample_papers()
            if not papers:
                return jsonify({"query": query, "papers": []})
            result = {
                "query": query,
                "papers": embed_and_rank(query, papers),
                "status": "offline",
                "refinement_rounds": 0,
                "search_queries_used": [query],
                "acceptance_reason": "offline_mode",
            }
        else:
            result = run_search_agent(query)
    except SemanticScholarError as exc:
        print(f"[search] API error: {exc}", flush=True)
        return jsonify({"error": str(exc)}), 503

    ranked = result["papers"]
    print(f"[search] retrieved {len(ranked)} papers status={result['status']}", flush=True)

    if ranked:
        top = ranked[0]
        print(
            f"[search] top result: {top.get('title')} "
            f"(score={top.get('relevance_score', 0):.4f})",
            flush=True,
        )
    print(f"[search] done in {time.perf_counter() - started:.1f}s", flush=True)
    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
