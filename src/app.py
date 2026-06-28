"""
Flask web server — 1st baseline retrieval (no agent/LLM).
"""

import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from src.artifacts import save_run_artifacts
from src.fetch import SurveyConfig
from src.history import get_search, list_history, save_search
from src.pipeline import run_retrieval
from src.rank import embed_and_rank
from src.tools import load_sample_papers

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app = Flask(__name__, static_folder=str(STATIC_DIR))

_CONFIG_KEYS = {
    "timeline_from_year",
    "timeline_to_year",
    "fields_of_study",
    "year_chunk_fetch",
    "expand_acronyms",
    "strict_timeline_filter",
    "min_relevance_score",
    "display_limit",
    "sources",
    "rank_method",
}


def _config_overrides(body: dict) -> dict:
    overrides = body.get("config") or {}
    if not isinstance(overrides, dict):
        return {}
    flat = {k: body[k] for k in _CONFIG_KEYS if k in body}
    return {**overrides, **flat}


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/config")
def get_config():
    return jsonify(SurveyConfig.load().to_public_dict())


@app.post("/search")
def search():
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()
    offline = bool(body.get("offline", False))
    survey_mode = bool(body.get("survey_mode", False))

    if not query:
        return jsonify({"error": "query is required"}), 400

    started = time.perf_counter()
    overrides = _config_overrides(body)
    print(f"[search] query={query!r} source={'offline' if offline else 'live'}", flush=True)

    if offline:
        papers = load_sample_papers()
        ranked = embed_and_rank(query, papers) if papers else []
        config = SurveyConfig.load().apply_overrides(overrides)
        display = ranked[: config.display_limit]
        result = {
            "query": query,
            "search_query": query,
            "search_queries": [query],
            "config": config.to_public_dict(),
            "papers": ranked,
            "papers_display": display,
            "rejects": [],
            "status": "offline",
            "metrics": {
                "latency_ms": 0,
                "api_calls": 0,
                "cache_hits": 0,
                "papers_accepted": len(ranked),
                "papers_display": len(display),
            },
            "fetch_errors": [],
        }
    else:
        result = run_retrieval(
            query,
            config_overrides=overrides,
            survey_mode=survey_mode,
        )
        if result.get("metrics"):
            result["metrics"]["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)

    display_count = len(result.get("papers_display") or [])
    corpus_count = len(result.get("papers") or [])
    print(
        f"[search] corpus={corpus_count} display={display_count} status={result['status']}",
        flush=True,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

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
