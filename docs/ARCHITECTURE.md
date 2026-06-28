# Architecture — 1st baseline retrieval

This document records design decisions for the scripted paper retrieval baseline.

## Scope

**In:** fetch Semantic Scholar + arXiv + **OpenAlex** → normalize → dedupe → persist → rank → screen → full corpus + display preview.  
**Out:** Ollama/agent, single/multi-agent (future tiers).

Current design doc: **`flowcharts/flowchart_v5.md`** (v4 frozen).

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
| **`src/loop_control.py`** | `query_state` read/write (G1/G2) |
| **`src/store.py`** | `papers.db`, `paper_identifiers`, upsert with merge-on-lookup (E3) |
| **`src/normalize.py`** | Raw records → `PaperRecord` |
| **`src/rank.py`** | SBERT primary + lexical secondary |
| **`src/schema.py`** | `PaperRecord`, IDs, dedupe keys |
| **`src/config.py`** | Paths, env, constants |
| **`src/main.py`, `src/app.py`, `src/eval.py`** | Entry points (CLI, web, benchmark) |
| **`src/history.py`, `src/artifacts.py`** | Optional run persistence |
| **`private/`** | Your local notes/files — gitignored, not part of the codebase |
| **`data/survey_config.json`** | Runtime config |

---

## Pipeline

```
User query
  │
  ├─► [1] Load local corpus (papers.db, same query via source_hits)
  │
  └─► [2] Live fetch (SS + arXiv + OpenAlex)
         │
         ├─► Raw API response → SQLite cache shard (TTL = cache_ttl_days)
         │
         ├─► Normalize → PaperRecord
         ├─► Dedupe within fetch (merge SS + arXiv by paper_id)
         └─► Upsert → papers.db (main normalized corpus)

  [3] Merge local + live → dedupe in-run pool
  [4] Rank full pool — **SBERT primary** + **lexical_v1 secondary** (+ TF-IDF/recency aux)
  [5] Screen (min_relevance_score, optional strict timeline)
  [6] Record query_state (G2)
  [7] Return papers (full accepted corpus) + papers_display (preview N)
```

`RAW cache (3 shards/source) → normalize → dedupe → main DB → screen`.

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

## Year-chunking (“cache in chunks”)

fetch/cache by year slices (2020, 2021, …) instead of one huge `2020-2026` request.

**What it means here:**

- Semantic Scholar calls use `year=2020`, then `year=2021`, etc. (`year_chunk_fetch: true` in config).
- Each `(query, year, offset)` is a **separate raw cache entry**.
- Normalize/upsert happens **after each chunk** — lower peak memory than one giant response.
- On repeat runs, cached years skip network even if other years are new.

**What it is not:** text chunking for RAG embeddings (that belongs in the downstream RAG tier).

arXiv has no year API param; it uses query + pagination only.

---

## Local DB + live API (continuous curation)

`papers.db` is **not** write-only anymore.

On each query:

1. **Read** papers previously fetched for this exact query (`source_hits.query`).
2. **Fetch** live from APIs (with raw cache).
3. **Upsert** new papers.
4. **Merge** local + live, rank the **full pool**.

Second search for the same query returns cached corpus instantly plus any new API results. Cross-query corpus reuse (e.g. FTS over all papers) is future work.

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

Use lexical for debugging, export, or future rerank — not for primary benchmark ranking unless explicitly switched later.

---

## Dedupe — identifier alignment (E1–E3)

**E1 — Align keys:** `paper_dedupe_key()` and in-run dedupe both delegate to `canonical_paper_id_from_dict()` with fixed priority: DOI → arXiv → OpenAlex → S2 → title hash.

**E2 — Identifier table:** `paper_identifiers (paper_id, id_type, id_normalized)` indexes DOI, arXiv, S2, OpenAlex IDs.

**E3 — Merge on lookup:** Before insert, `upsert_papers_batch` resolves `paper_id` via identifier table (then existing `papers` row). If a new record shares any identifier with an existing paper, fields merge into the canonical row instead of creating a duplicate.

---

## Loop control — query_state (G1–G2)

**G1 — Table:** `query_state` per query string: `last_run_at`, `accepted_count`, `rejected_count`, `error_count`, `consecutive_zero_accept`.

**G2 — Record after run:** Pipeline calls `record_query_outcome()` after screening. `consecutive_zero_accept` increments when a run accepts zero papers; resets on any accept. Foundation for future dead-query drop rules — not enforced yet.

---

## Ranking vs “agent”

| Component | 1st baseline? |
|-----------|----------------|
| SBERT (`all-MiniLM-L6-v2`) | Yes — primary rank (pinned package) |
| Lexical (`baseline_lexical_v1`) | Yes — secondary explainable score |
| TF-IDF / recency | Yes — auxiliary metrics |
| Ollama / LLM | No — removed |
| Quality gate (`results_acceptable`) | No — was agent trigger only |

Embeddings for ranking are **not** the agent tier; they are standard IR.

---

## Eval, `--no-cache`, and `--official`

`python -m src.eval` runs the benchmark JSON (28 queries).

**`--no-cache` / `--official`:** bypass raw cache shards, force live API calls. `--official` is an alias for `--no-cache` plus recommended reporting mode.

Use when measuring true fetch latency, after fetch/normalize changes, or before publishing benchmark numbers.

Eval JSON records: `cache_enabled`, `benchmark_sha256`, `embedding_model`, `embedding_package_version`, `lexical_scorer`.

---

## Reproducibility

Pinned for official runs:

- `sentence-transformers==5.5.1` in `requirements.txt`
- `embedding_package_version()` in eval metadata
- `benchmark_sha256` of `data/benchmark_queries.json`
- Run `python -m src.eval --official` for reported numbers
