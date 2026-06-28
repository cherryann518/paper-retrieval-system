# Pipeline flowchart v5 — 1st baseline (three providers + cache TTL)

Deterministic retrieval: SS + arXiv + **OpenAlex**, sharded SQLite raw cache with **TTL**, FTS cross-query prefetch (optional), fuzzy duplicate flags, full accepted corpus + display preview + NDJSON export.

*(v4 is frozen; v5 supersedes it for current design.)*

---

## One sentence

User query → canonical queries → **same-query local corpus** + optional **FTS cross-query prefetch** → fetch **3 providers in parallel** (429-throttled) → normalize & dedupe → upsert main DB + **fuzzy duplicate flags** → rank (SBERT + lexical + D4 title/abstract SBERT) → screen (min score + optional D3 dual-gate) → **`ranked_pool` + accepted corpus + display preview** → optional **NDJSON export**.

---

## Main flow

```mermaid
flowchart TD
    Start["User query<br/>CLI · web · eval · survey mode"]

    subgraph config [Config]
        Survey["survey_config.json<br/>sources, years, cache_ttl_days,<br/>dual_gate_screening, fts_prefetch"]
        Env[".env<br/>S2 key · OpenAlex mailto"]
    end

    subgraph local [Local corpus]
        LocalDB[("papers.db")]
        SameQ["Prior papers same query<br/>source_hits"]
        FTS["FTS5 prefetch<br/>papers_fts optional"]
    end

    subgraph loopctl [Loop control]
        QState["query_state<br/>per sub-query + user query<br/>dead-query skip in survey"]
    end

    subgraph fetch [Live fetch — parallel, 429-throttled]
        SS["Semantic Scholar"]
        Arxiv["arXiv"]
        OA["OpenAlex"]
        Cache[("Raw cache<br/>3 SQLite shards / source<br/>TTL expiry")]
        Throttle["FetchThrottle"]
    end

    subgraph integrate [Normalize & persist]
        Norm["PaperRecord"]
        IdMerge["Identifier merge E3"]
        Fuzzy["possible_duplicates E4"]
        MainDB[("papers.db + screening_decisions")]
    end

    subgraph rankout [Rank & output]
        Rank["rank_papers<br/>sbert · lexical · D4 title/abstract"]
        Pool["ranked_pool pre-screen"]
        Screen["apply_screening<br/>min_score · D3 dual-gate"]
        Corpus["papers accepted corpus"]
        Display["papers_display preview"]
        NDJSON["corpus.ndjson export"]
    end

    Start --> config
    config --> QState
    QState --> LocalDB
    LocalDB --> SameQ
    LocalDB --> FTS
    config --> Throttle
    Throttle --> SS & Arxiv & OA
    SS & Arxiv & OA <-->|"hit/miss/TTL"| Cache
    SS & Arxiv & OA --> Norm --> IdMerge --> Fuzzy --> MainDB
    SameQ --> Rank
    FTS --> Rank
    Rank --> Pool --> Screen
    Screen --> Corpus --> Display
    Corpus --> NDJSON
    Screen --> QState
```

---

## v5 feature summary

| Item | Description |
|------|-------------|
| Providers | SS + arXiv + OpenAlex (parallel fetch) |
| Cache | 3 SQLite shards/source + `cache_ttl_days` |
| Output | `ranked_pool` + accepted corpus + display preview + NDJSON |
| Scoring | SBERT primary + lexical secondary + D4 title/abstract SBERT |
| D3 | Optional dual-gate (high SBERT + low lexical → reject) |
| Dedupe E1–E4 | Identifier merge + fuzzy flag |
| G1–G3 | Per-sub-query `query_state` + dead-query skip |
| G4 | FTS5 cross-query prefetch (default off) |
| G5 | `FetchThrottle` on 429 burst |
| Eval | pool / accepted / display target metrics; per-query config |

---

## Config toggles (survey_config.json)

```json
{
  "research_questions": ["..."],
  "query_hints": ["..."],
  "fts_prefetch_enabled": false,
  "fuzzy_dedupe_enabled": true,
  "dual_gate_screening": false,
  "dual_gate_sbert_min": 0.35,
  "dual_gate_lexical_max": 0.15,
  "dual_gate_delta_min": 0.25,
  "dead_query_threshold": 3,
  "rate_limit_threshold": 2
}
```

---

## Entry points

| Command | Purpose |
|---------|---------|
| `python3 -m src.main "topic"` | CLI search |
| `python3 -m src.main "topic" --export ndjson` | Search + NDJSON corpus |
| `python3 -m src.main "topic" --survey` | Multi-query + dead-query skip |
| `python3 -m src.app` | Web UI |
| `python -m src.eval --official` | Reproducible benchmark → `OFFICIAL_BASELINE.json` |
| `python -m src.eval --skip-screening` | Retrieval-only benchmark |

---

## Module map

```text
src/pipeline.py       run_retrieval() — ranked_pool + papers + rejects
src/export.py         NDJSON corpus export
src/eval.py           benchmark + official baseline
src/fetch.py          fetch_all_sources() — parallel + throttle
src/store.py          papers.db, FTS5, possible_duplicates
src/screening.py      accept/reject + D3 dual-gate
src/rank.py           SBERT + lexical + D4 field scores
src/loop_control.py   query_state + dead-query filter
```
