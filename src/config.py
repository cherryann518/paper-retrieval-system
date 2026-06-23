"""
Configuration settings for the paper retrieval system.

Centralizes paths (data/, outputs/), API keys, rate limits, default search
providers, and other runtime options. Values may be loaded from environment
variables or a local config file.
"""

import os
from pathlib import Path

# Project root (parent of src/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Load .env into os.environ (does not override existing env vars)."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
CACHE_DIR = OUTPUTS_DIR / "cache"
PAPERS_DB_PATH = OUTPUTS_DIR / "papers.db"

DEFAULT_MAX_RESULTS = 10
MAX_CANDIDATES_PER_RUN = 200
TIMELINE_FROM_YEAR = 2020
TIMELINE_TO_YEAR = 2026

# Semantic Scholar API (set SEMANTIC_SCHOLAR_API_KEY in .env or environment)
SEMANTIC_SCHOLAR_API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
SEMANTIC_SCHOLAR_MIN_INTERVAL = 1.0  # 1 request/sec with API key

# Agent retrieval
SEMANTIC_SCHOLAR_FETCH_LIMIT = 100  # papers per API call (Semantic Scholar max)
MAX_PAGES_PER_QUERY = 2  # paginated fetches per search query (offset += limit)
MAX_RESULTS_RETURN = 10  # top-N papers returned after embedding rank
MAX_REFINEMENT_ROUNDS = 2
RUNS_DIR = OUTPUTS_DIR / "runs"
EVAL_DIR = OUTPUTS_DIR / "eval"

# Scoring thresholds (all-MiniLM-L6-v2 cosine similarity)
SCORE_GOOD = 0.40
SCORE_TOP_MIN = 0.35
MIN_GOOD_PAPERS = 3
MIN_SCORE_GAP = 0.08

# Ollama (local query refinement)
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
OLLAMA_TIMEOUT = 60

# Search history retention (days)
HISTORY_RETENTION_DAYS = 60  # ~2 months
