# Architecture — 1st baseline retrieval

This document records design decisions for the scripted paper retrieval baseline.

## Scope

**In:** fetch Semantic Scholar + arXiv + **OpenAlex** → normalize → dedupe → persist → rank → screen → full corpus + display preview.  

Current design doc: **`flowcharts/flowchart_v5.md`** (v4 frozen).  
**Rigorous combined diagram:** [SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md) (pipeline + components + Jincheng comparison).

## Repo layout

| Path | Role |
|------|------|
| **`src/pipeline.py`** | Orchestrator — `run_retrieval()` |
| **`src/query_builder.py`** | Canonical queries from config |
| **`src/screening.py`** | Accept/reject + reasons |
| **`src/fetch.py`** | Multi-source fetch, `SurveyConfig`, year-chunking |
| **`src/sources/`** | SS, arXiv, OpenAlex adapters |
| **`src/lexical.py`** | `baseline_lexical_v1` explainable secondary score |
| **`src/identifiers.py`** | ID normalization + dedupe key alignment (E1) |
| **`src/fuzzy_dedupe.py`** | E4 fuzzy title+year duplicate flagging |
| **`src/rate_throttle.py`** | G5 429 burst throttle for parallel fetch |
| **`src/loop_control.py`** | `query_state`, dead-query skip (G1–G3) |
| **`src/store.py`** | `papers.db`, identifiers, FTS5, `possible_duplicates`, upsert |
| **`src/normalize.py`** | Raw records → `PaperRecord` |
| **`src/rank.py`** | SBERT primary + lexical secondary |
| **`src/schema.py`** | `PaperRecord`, IDs, dedupe keys |
| **`src/config.py`** | Paths, env, constants |
| **`src/main.py`, `src/app.py`, `src/eval.py`** | Entry points (CLI, web, benchmark) |
| **`src/export.py`** | NDJSON corpus export for RAG downstream |
| **`src/history.py`, `src/artifacts.py`** | Optional run persistence |
| **`private/`** | Your local notes/files — gitignored, not part of the codebase |
| **`data/survey_config.json`** | Runtime config |

---

## Pipeline

```
User query
  │
  ├─► [0] Loop control — skip dead queries in survey mode (G3)
  │
  ├─► [1] Load local corpus
  │       ├─ same query via source_hits
  │       └─ optional FTS5 cross-query prefetch (G4, fts_prefetch_enabled)
  │
  └─► [2] Live fetch (SS + arXiv + OpenAlex, parallel, 429-throttled G5)
         │
         ├─► Raw API response → SQLite cache shard (TTL = cache_ttl_days)
         │
         ├─► Normalize → PaperRecord
         ├─► Dedupe within fetch (merge by paper_id)
         └─► Upsert → papers.db
               ├─ identifier merge (E3)
               ├─ FTS index sync (G4)
               └─ fuzzy duplicate flags (E4)

  [3] Merge local + live → dedupe in-run pool
  [4] Rank — SBERT primary + lexical secondary + D4 title/abstract SBERT
  [5] Screen (min_relevance_score + optional D3 dual-gate)
  [6] Record query_state per sub-query + original (G2/H1)
  [7] Return ranked_pool + papers + papers_display + rejects + metrics
```

**Pipeline outputs:**

| Field | Meaning |
|-------|---------|
| `ranked_pool` | Full ranked list **before** screening (retrieval eval) |
| `papers` | Accepted corpus (for RAG / NDJSON export) |
| `papers_display` | Top `display_limit` preview |
| `rejects` | Screened-out papers with auditable reasons |

`RAW cache (3 shards/source) → normalize → dedupe → main DB → rank → screen → export`.

---

## Raw cache — 3 SQLite shards per source

**Requirement:** one cache DB (or one flat store) per source would grow too
large for RAM — loading or scanning it blows the working set when paper volume is high.

**What we do:** **3 shard SQLite files per source** (`shard_0.sqlite` … `shard_2.sqlite`).
Each raw API response lands in exactly one shard via `hash(cache_key) mod 3`. A lookup
opens **only that shard** — not the whole cache.

```text
outputs/cache/
  semantic_scholar/shard_0.sqlite  shard_1.sqlite  shard_2.sqlite
  arxiv/shard_0.sqlite             shard_1.sqlite  shard_2.sqlite
outputs/papers.db                  ← normalized corpus (separate)
```

| Question | Answer |
|----------|--------|
| Normalized or raw in cache? | **Raw** API JSON/XML — normalize happens when upserting `papers.db` |
| Why 3? | Fixed partition count; spreads entries so each file stays smaller in RAM |
| Relation to year-chunks? | Year-chunks limit **fetch** size; shards limit **cache DB** size — same goal, two layers |
| Legacy `.json` files? | Still read as fallback; new writes go to SQLite only |

Config: `CACHE_SHARDS_PER_SOURCE = 3` in `src/config.py`.

---

## CS-only vs general retrieval

Controlled by `fields_of_study` in `survey_config.json`:

```json
"fields_of_study": []                    → general (default)
"fields_of_study": ["Computer Science"]  → CS-only on Semantic Scholar
```

**Caveats:** arXiv has no equivalent filter; one global config applies to all queries (no per-query domain yet).

---

## Local DB + live API (continuous curation)

`papers.db` is **not** write-only anymore.

On each query:

1. **Read** papers previously fetched for this exact query (`source_hits.query`).
2. **Optional FTS prefetch** — when `fts_prefetch_enabled: true`, search `papers_fts` (title+abstract) for cross-query hits up to `fts_prefetch_limit`.
3. **Fetch** live from APIs (parallel; throttled to serial after 429 burst).
4. **Upsert** new papers (identifier merge + fuzzy flags + FTS sync).
5. **Merge** local + live, rank the **full pool**.

Second search for the same query returns cached corpus instantly plus any new API results. With FTS enabled, related papers from *other* past queries enter the pool without re-fetching.

---

## Pool cap removed

Previously `max_candidates_per_run: 200` truncated after merge with **undefined order** (source-order bias).

**Decision:** no artificial cap. Pagination runs until:

- API returns fewer than `limit` papers, or  
- SS offset exceeds ~900, or  
- `MAX_PAGES_PER_QUERY` pages per year-chunk (safety bound, default 10).

---

## Acronym expansion (design choice)

Hardcoded map: `RAG` → `retrieval augmented generation`, etc.

| | **expand_acronyms: false (default)** | **expand_acronyms: true** |
|---|--------------------------------------|---------------------------|
| Determinism | Fully literal query | Hidden rewrite for single tokens |
| CS queries | User must type full phrase | `RAG` works out of the box |
| Biology/other | No wrong CS bias | No effect on multi-word queries |
| Benchmark | Tests real user input | Confounds “query quality” with hidden policy |

**Recommendation:** keep **`false`** for the 1st baseline. Document known acronyms in benchmark notes; let tier-2 (LLM query) handle expansion later.

Config: `"expand_acronyms": false` in `data/survey_config.json`.

---

## fields_of_study filter (open problem)

`survey_config.json` can set `"fields_of_study": ["Computer Science"]`.

**Problem:** SS applies this to **every** query. Cross-domain benchmark queries (biology, geology, …) silently fail or return wrong-domain papers.

**Current default:** `"fields_of_study": []` (no filter) — general retrieval.


---

## Dual scoring (SBERT + lexical)

**Primary sort / screening input:** SBERT cosine similarity (`rank_method: "sbert"` default).

**Secondary explainable score:** `baseline_lexical_v1` in `src/lexical.py` — always computed and stored in `scores.lexical_v1` and `lexical_components`. It does **not** override SBERT sort order.

Weighted formula:

| Component | Weight | Meaning |
|-----------|--------|---------|
| `title_keyword_overlap` | 0.35 | Query token recall in title (stopwords removed) |
| `abstract_keyword_overlap` | 0.30 | Same for abstract |
| `query_phrase_match` | 0.15 | Full query substring in title (1.0) or abstract (0.7) |
| `recency_score` | 0.10 | Linear decay vs configured year window |
| `identifier_score` | 0.05 | 1.0 if DOI/arXiv present |
| `citation_score` | 0.05 | Log-scaled citation count |

Use lexical for debugging, export, or dual-gate screening — not for primary benchmark ranking unless explicitly switched later.

### D3 — Dual-gate screening (optional)

When `dual_gate_screening: true`, reject papers where SBERT is high but lexical is suspiciously low:

- `relevance_score >= dual_gate_sbert_min` (default 0.35)
- `lexical_v1 <= dual_gate_lexical_max` (default 0.15)
- `(sbert - lexical) >= dual_gate_delta_min` (default 0.25)

Reject reason: `semantic_lexical_divergence`. Default **`false`** in `survey_config.json`.

### D4 — Separate title/abstract SBERT

Every SBERT rank pass also stores:

- `scores.sbert_title_cosine` — query vs title only
- `scores.sbert_abstract_cosine` — query vs abstract only

Primary sort still uses `sbert_cosine` (title + abstract). Use field scores in `--json` / divergence diagnostics.

---

## NDJSON export (C4)

```bash
python3 -m src.main "topic" --export ndjson
```

Writes `outputs/runs/{run_id}/corpus.ndjson` — one JSON object per accepted paper (ids, scores, lexical components, query).

Module: `src/export.py`.

---

## Dedupe — identifier alignment (E1–E3)

**E1 — Align keys:** `paper_dedupe_key()` and in-run dedupe both delegate to `canonical_paper_id_from_dict()` with fixed priority: DOI → arXiv → OpenAlex → S2 → title hash.

**E2 — Identifier table:** `paper_identifiers (paper_id, id_type, id_normalized)` indexes DOI, arXiv, S2, OpenAlex IDs.

**E3 — Merge on lookup:** Before insert, `upsert_papers_batch` resolves `paper_id` via identifier table. Shared identifiers merge into one canonical row.

**E4 — Fuzzy title flag:** After upsert, `normalize_fuzzy_title()` + year tolerance (`|Δyear| ≤ 1`) matches against `title_normalized` index. Hits write to `possible_duplicates` — **never auto-merge**. Toggle: `fuzzy_dedupe_enabled` (default `true`). Metrics: `possible_duplicates_flagged`, `possible_duplicates_total`.

---

## FTS5 cross-query prefetch (G4)

**Virtual table:** `papers_fts (paper_id, title, abstract)` — synced on every upsert.

**When enabled** (`fts_prefetch_enabled: true` in config):

- Before live fetch, `search_corpus_fts(query, limit=fts_prefetch_limit)` pulls relevant papers from the full corpus regardless of prior `source_hits.query`.
- Default **`false`** — opt-in to avoid surprising cross-query contamination during dev/benchmark.

---

## Loop control — query_state (G1–G3)

**G1 — Table:** `query_state` per query: `last_run_at`, accept/reject/error counts, `consecutive_zero_accept`.

**G2 — Record after run:** Pipeline writes `query_state` for **each canonical sub-query** (papers attributed via `source_queries`) and for the original user query.

**G3 — Dead query drop:** In `--survey` mode, skip queries with `consecutive_zero_accept >= dead_query_threshold` (default 3). Primary user query always kept.

---

## Fetch throttle (G5)

Parallel provider fetch uses `ThreadPoolExecutor`. A shared `FetchThrottle` per pipeline run counts 429 / rate-limit errors; when `>= rate_limit_threshold` (default 2), subsequent fetches in the same run use **1 worker** (serial). Logged in metrics as `fetch_throttled`, `rate_limit_errors`.

---

## Eval, `--no-cache`, and `--official`

`python -m src.eval` runs `data/benchmark/queries.json` (28 queries).

| Flag | Effect |
|------|--------|
| `--no-cache` | Bypass raw cache shards |
| `--no-local` | Skip `papers.db` local corpus read |
| `--skip-screening` | Retrieval-only (no min_score / dual-gate) |
| `--official` | **`--no-cache` + `--no-local`**; writes `outputs/eval/OFFICIAL_BASELINE.json` |

**Target metrics (C1):**

| Column | Meaning |
|--------|---------|
| `dsp` | Target in display top-10 |
| `pool` | Target in pre-screen **ranked_pool** (retrieval) |
| `acc` | Target in accepted corpus (post-screening) |
| `rej` | Targets rejected by screening |

Per-query benchmark overrides: `"config": { "fields_of_study": ["Biology"] }` in benchmark JSON.

Eval JSON records: `benchmark_sha256`, `embedding_model`, `embedding_package_version`, `lexical_scorer`, `aggregate`, `local_corpus_enabled`, `skip_screening`.

---

## Reproducibility

Pinned for official runs:

- `sentence-transformers==5.5.1` in `requirements.txt`
- `embedding_package_version()` in eval metadata
- `benchmark_sha256` of `data/benchmark/queries.json`
- Run `python -m src.eval --official` then commit `outputs/eval/OFFICIAL_BASELINE.json`
