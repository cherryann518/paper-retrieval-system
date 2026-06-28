"""
Configuration: paths, API keys, rate limits, and runtime defaults.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
CACHE_DIR = OUTPUTS_DIR / "cache"
CACHE_SHARDS_PER_SOURCE = 3  # SQLite shard DBs per source (RAM / working-set limit)
DEFAULT_CACHE_TTL_DAYS = 7  # raw API cache expiry; 0 = never expire
OPENALEX_MAX_PER_PAGE = 200
OPENALEX_MIN_INTERVAL = 0.2  # polite pool with mailto; increase if no mailto
PAPERS_DB_PATH = OUTPUTS_DIR / "papers.db"
RUNS_DIR = OUTPUTS_DIR / "runs"
EVAL_DIR = OUTPUTS_DIR / "eval"
DEFAULT_CONFIG_PATH = DATA_DIR / "survey_config.json"
HISTORY_RETENTION_DAYS = 60

SEMANTIC_SCHOLAR_FETCH_LIMIT = 100
SEMANTIC_SCHOLAR_MAX_OFFSET = 900
SEMANTIC_SCHOLAR_MIN_INTERVAL = 1.0
MAX_PAGES_PER_QUERY = 10
DISPLAY_LIMIT = 10  # CLI / web preview count
ARXIV_MAX_RESULTS = 100
DEAD_QUERY_THRESHOLD = 3  # consecutive zero-accept runs before skip in survey mode
RATE_LIMIT_THRESHOLD = 2  # 429 errors in one fetch before throttling to serial
DEFAULT_FTS_PREFETCH_LIMIT = 50

# D3 dual-gate screening (SBERT high + lexical low → reject)
DEFAULT_DUAL_GATE_SCREENING = False
DUAL_GATE_SBERT_MIN = 0.35
DUAL_GATE_LEXICAL_MAX = 0.15
DUAL_GATE_DELTA_MIN = 0.25

OFFICIAL_BASELINE_PATH = EVAL_DIR / "OFFICIAL_BASELINE.json"

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_PACKAGE_PIN = "sentence-transformers==5.5.1"


def embedding_package_version() -> str:
    try:
        import importlib.metadata as metadata

        return metadata.version("sentence-transformers")
    except Exception:
        return "unknown"

ML_ACRONYM_EXPANSIONS: dict[str, str] = {
    "rag": "retrieval augmented generation",
    "llm": "large language models",
    "llms": "large language models",
}


def _load_dotenv() -> None:
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

SEMANTIC_SCHOLAR_API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
# OpenAlex: no API key. Optional mailto= for polite pool (higher rate limits).
OPENALEX_MAILTO = os.environ.get("OPENALEX_MAILTO", "")
OPENALEX_BASE_URL = os.environ.get("OPENALEX_BASE_URL", "https://api.openalex.org")
