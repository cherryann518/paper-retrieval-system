# Paper Retrieval System — 1st baseline (v5)

Scripted retrieval: Semantic Scholar + arXiv + OpenAlex → normalize → dedupe → rank → screen → persist.

**Not in scope:** Ollama/agent, single/multi-agent tiers.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/SYSTEM_ARCHITECTURE.md`](docs/SYSTEM_ARCHITECTURE.md), and [`flowcharts/flowchart_v5.md`](flowcharts/flowchart_v5.md).

---

## Quick start

```bash
source .venv/bin/activate
pip install -r requirements.txt   # pins sentence-transformers==5.5.1

cp .env.example .env
# Set SEMANTIC_SCHOLAR_API_KEY and OPENALEX_MAILTO (no OpenAlex API key needed)
```

### CLI

```bash
python3 -m src.main "retrieval augmented generation"
python3 -m src.main "topic" --json
python3 -m src.main "topic" --export ndjson   # writes corpus.ndjson in run artifacts
python3 -m src.main "topic" --survey
python3 -m src.main "topic" --no-cache
python3 -m src.main --offline "topic"
```

### Eval (28-query benchmark)

```bash
python -m src.eval --official          # no cache + no local corpus → OFFICIAL_BASELINE.json
python -m src.eval --official --skip-screening   # retrieval-only
python -m src.eval --no-cache
python -m src.eval --no-local
python -m src.eval
```

Eval columns: `dsp` (display), `pool` (pre-screen ranked), `acc` (accepted), `rej` (targets lost to screening).

Eval JSON includes: `benchmark_sha256`, `aggregate`, `local_corpus_enabled`, `skip_screening`, embedding + lexical versions.

---

## Response shape

| Field | Purpose |
|-------|---------|
| `ranked_pool` | Full ranked list **before** screening (retrieval eval) |
| `papers` | Full **accepted** ranked corpus (RAG downstream) |
| `papers_display` | Preview slice (`display_limit`, default 10) |
| `rejects` | Screened-out papers with reasons |
| Per paper: `scores.sbert_cosine`, `scores.sbert_title_cosine`, `scores.sbert_abstract_cosine`, `scores.lexical_v1` | Dual + D4 field scores |

---

## Scoring

- **Primary rank:** SBERT (`all-MiniLM-L6-v2`) — sort order and screening input
- **Secondary:** `baseline_lexical_v1` — weighted keyword/metadata formula (always computed, stored in `scores`)

---

## Config (`data/survey_config.json`)

Key fields: `sources`, `timeline_*`, `fields_of_study`, `min_relevance_score`, `dual_gate_screening`, `display_limit`, `cache_ttl_days`, `research_questions`, `query_hints`, `fts_prefetch_enabled`.

`fields_of_study: []` = general retrieval (default).

---

## Outputs

| Path | Contents |
|------|----------|
| `outputs/papers.db` | Corpus + `paper_identifiers` + `query_state` + `screening_decisions` |
| `outputs/cache/{source}/shard_*.sqlite` | Raw API cache with TTL |
| `outputs/runs/{id}/` | Per-run artifacts |
| `outputs/runs/{id}/corpus.ndjson` | NDJSON export (`--export ndjson`) |
| `outputs/eval/OFFICIAL_BASELINE.json` | Official benchmark (`--official`) |
