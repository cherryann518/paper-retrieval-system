"""
Flask web server for the paper retrieval pipeline.

Serves a minimal frontend and exposes POST /search for ranked paper results.
"""

import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from src.agent import run_search_agent
from src.artifacts import save_run_artifacts
from src.history import get_search, list_history, save_search
from src.tools import embed_and_rank, load_sample_papers

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
            "mode": "offline",
            "rounds": [],
            "metrics": {"latency_ms": 0, "api_calls": 0, "ollama_calls": 0},
            "fetch_errors": [],
        }
    else:
        result = run_search_agent(query)
        if result.get("metrics"):
            result["metrics"]["latency_ms"] = round(
                (time.perf_counter() - started) * 1000, 1
            )

    ranked = result["papers"]
    print(
        f"[search] retrieved {len(ranked)} papers status={result['status']}",
        flush=True,
    )

    if ranked:
        top = ranked[0]
        print(
            f"[search] top result: {top.get('title')} "
            f"(score={top.get('relevance_score', 0):.4f})",
            flush=True,
        )

    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"[search] done in {elapsed_ms / 1000:.1f}s", flush=True)

    if not offline:
        try:
            run_dir = save_run_artifacts(result)
            result["run_id"] = run_dir.name
            result["history_id"] = save_search(result, duration_ms=elapsed_ms)
        except OSError as exc:
            print(f"[history] save failed: {exc}", flush=True)

    return jsonify(result)


@app.get("/history")
def history_list():
    return jsonify({"items": list_history()})


@app.get("/history/<int:session_id>")
def history_detail(session_id: int):
    item = get_search(session_id)
    if item is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(item)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
