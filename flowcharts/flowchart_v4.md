# Pipeline flowchart v4 — 1st baseline (scripted)

Deterministic retrieval — modular `src/` packages, orchestrated by `src/pipeline.py`.

---

## One sentence

User query (+ optional survey config queries) → local corpus + fetch SS & arXiv (raw-cached, year-chunked) → normalize & dedupe → upsert main DB → rank full pool → screen → **full accepted corpus** + **display preview**.

---

## Main flow

```mermaid
flowchart TD
    Start["User query<br/>CLI · web · eval"]

    subgraph config [Config]
        Survey["survey_config.json<br/>years, sources, rank_method,<br/>min_score, display_limit, RQs"]
        Overrides["UI / API overrides"]
    end

    subgraph queries [Query plan]
        QB["build_canonical_queries<br/>user query · survey mode adds RQs"]
    end

    subgraph local [Local corpus read]
        LocalDB[("papers.db<br/>source_hits match")]
        LocalPapers["Prior papers per query"]
    end

    subgraph fetch [Live fetch per source]
        YearLoop["Year chunks per SS call"]
        SS["Semantic Scholar"]
        Arxiv["arXiv"]
        RawSS[("3× SQLite shards<br/>semantic_scholar/")]
        RawAx[("3× SQLite shards<br/>arxiv/")]
    end

    subgraph integrate [Normalize & persist]
        Norm["PaperRecord"]
        DedupeFetch["Dedupe by paper_id"]
        MainDB[("papers.db upsert")]
    end

    subgraph rankout [Rank, screen, output]
        Pool["Merge local + live"]
        Rank["rank_papers"]
        Screen["apply_screening<br/>min_score · timeline"]
        Corpus["papers — full accepted corpus<br/>(RAG downstream)"]
        Display["papers_display — preview N<br/>(CLI / web cards)"]
        Rejects[("screening_decisions")]
        Artifacts["outputs/runs/{id}/"]
    end

    Start --> config
    config --> QB
    QB --> LocalDB
    LocalDB --> LocalPapers
    QB --> YearLoop
    YearLoop --> SS
    config --> Arxiv
    SS <-->|"hit / miss"| RawSS
    Arxiv <-->|"hit / miss"| RawAx
    SS --> Norm
    Arxiv --> Norm
    Norm --> DedupeFetch
    DedupeFetch --> MainDB
    LocalPapers --> Pool
    DedupeFetch --> Pool
    Pool --> Rank
    Rank --> Screen
    Screen --> Corpus
    Screen --> Rejects
    Corpus --> Display
    Corpus --> Artifacts
    Display --> Artifacts
```

---

## Return vs display

| Output | Default | Consumer |
|--------|---------|----------|
| `papers` | All accepted after screening | RAG, artifacts, `--json` |
| `papers_display` | First `display_limit` (10) | Terminal preview, web cards |
| `rejects` | All screened out | Audit / DB |

Rank and screen run on the **full pool**; only the preview is capped.

---

## Storage layout

| Layer | Files | Role |
|-------|-------|------|
| Raw cache | 3× `shard_*.sqlite` per source (6 for SS+arXiv) | Raw API payloads; one shard opened per lookup |
| Corpus | `papers.db` | Normalized merged papers + screening audit |
| History | `history.db` | Web sessions (optional) |

| Command | Purpose |
|---------|---------|
| `python3 -m src.main "topic"` | CLI preview + artifacts |
| `python3 -m src.main "topic" --json` | Full corpus JSON |
| `python3 -m src.main "topic" --survey` | All config queries |
| `python3 -m src.app` | Web UI + `GET /config` filters |
| `python -m src.eval` | 28-query benchmark |

---

## Out of scope (v4)

- Ollama / query rewriting
- OpenAlex (future)
- Single-agent / multi-agent tiers

---

## Module map

```text
src/pipeline.py       run_retrieval()
src/query_builder.py  canonical query list
src/screening.py      accept / reject + reasons
src/fetch.py          SurveyConfig, fetch_all_sources
src/store.py          papers.db + screening_decisions
src/rank.py           SBERT / TF-IDF / recency
```
