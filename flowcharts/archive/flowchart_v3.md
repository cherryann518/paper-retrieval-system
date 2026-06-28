# Pipeline flowchart v3 — Retrieval Subsystem

Full layered architecture for continuous knowledge curation baseline.
See also: [flowchart_v2.md](flowchart_v2.md) (UI/agent loop focus).

---

## 1. System layers (bird's-eye)

```mermaid
flowchart TD
    subgraph config [Configuration]
        SurveyConfig["survey_config.json<br/>sources, timeline, rank_method"]
        EnvConfig[".env + src/config.py<br/>API keys, thresholds, limits"]
    end

    subgraph entry [Entry points]
        CLI["src/main.py"]
        Web["src/app.py"]
        Eval["src/eval.py"]
    end

    subgraph planner [Query planner layer]
        Agent["run_search_agent()"]
        Ollama["ollama_refine_query()"]
        Gate["results_acceptable()"]
    end

    subgraph retrieval [Retrieval pipeline]
        Fetch["fetch_all_sources()"]
        SS["Semantic Scholar adapter"]
        Arxiv["arXiv adapter"]
        Cache["outputs/cache/{source}/"]
        Normalize["normalize_s2 / normalize_arxiv"]
        Dedupe["merge_paper_records + dedupe_papers"]
        Store["upsert_papers_batch()"]
        MainDB[("outputs/papers.db")]
    end

    subgraph ranklayer [Ranking layer]
        Rank["rank_papers()"]
        SBERT["sbert_cosine"]
        TFIDF["tfidf_cosine"]
        Recency["recency"]
        Primary["primary_method picks sort key"]
    end

    subgraph persist [Persistence and output]
        Artifacts["outputs/runs/{run_id}/"]
        History[("outputs/history.db")]
        TopK["Top 10 papers returned"]
    end

    SurveyConfig --> Agent
    EnvConfig --> Agent
    CLI --> Agent
    Web --> Agent
    Eval --> Agent

    Agent --> Fetch
    Fetch --> SS
    Fetch --> Arxiv
    SS --> Cache
    Arxiv --> Cache
    Cache --> Normalize
    Normalize --> Dedupe
    Dedupe --> Store
    Store --> MainDB
    Dedupe --> Rank
    Rank --> SBERT
    Rank --> TFIDF
    Rank --> Recency
    SBERT --> Primary
    TFIDF --> Primary
    Recency --> Primary
    Primary --> Gate
    Gate -->|"weak"| Ollama
    Ollama -->|"new search string"| Fetch
    Gate -->|"ok or exhausted"| TopK
    TopK --> Artifacts
    TopK --> History
```

---

## 2. One search round (live path)

```mermaid
sequenceDiagram
    participant User
    participant Agent as run_search_agent
    participant Fetch as fetch_all_sources
    participant SS as Semantic Scholar
    participant Arxiv as arXiv API
    participant Cache as outputs/cache
    participant Norm as normalize
    participant DB as papers.db
    participant Rank as rank_papers
    participant Ollama

    User->>Agent: topic string
    Note over Agent: rank_topic = original topic<br/>(acronym expansion only)

    loop up to 3 rounds
        Agent->>Fetch: search_query, offset pages
        Fetch->>Cache: lookup hash key
        alt cache miss
            Fetch->>SS: GET paper/search
            Fetch->>Arxiv: GET api/query
            SS-->>Cache: store raw JSON
            Arxiv-->>Cache: store raw XML
        else cache hit
            Cache-->>Fetch: replay response
        end
        Fetch->>Norm: raw records per source
        Norm-->>Fetch: PaperRecord list
        Fetch-->>Agent: merged PaperRecords + stats
        Agent->>DB: upsert_papers_batch (chunks of 50)
        Agent->>Agent: dedupe in-run pool
        Agent->>Rank: rank_topic + paper dicts
        Note over Rank: compute ALL metrics<br/>sort by primary_method only
        Rank-->>Agent: ranked papers + scores dict
        Agent->>Agent: results_acceptable?
        alt weak and refinements left
            Agent->>Ollama: original topic + weak results + reason
            Ollama-->>Agent: new search_query
        else done
        end
    end

    Agent-->>User: top 10 + status + metrics
```

---

## 3. Data transformation chain

```mermaid
flowchart LR
    subgraph raw [Raw API payloads]
        S2JSON["S2 JSON per paper"]
        ArxivXML["arXiv Atom entry"]
    end

    subgraph canonical [Canonical schema]
        PR["PaperRecord<br/>src/schema.py"]
    end

    subgraph runtime [In-memory agent dict]
        AD["title, authors, year,<br/>abstract, externalIds,<br/>paper_id, sources"]
    end

    subgraph ranked [Ranked output dict]
        RD["+ relevance_score<br/>+ scores sbert/tfidf/recency<br/>+ rank_method"]
    end

    S2JSON -->|"normalize_s2()"| PR
    ArxivXML -->|"normalize_arxiv()"| PR
    PR -->|"to_agent_dict()"| AD
    AD -->|"rank_papers()"| RD
```

---

## 4. Identity and deduplication

```mermaid
flowchart TD
    Incoming["New paper from any source"]
    CheckDOI{"DOI present?"}
    CheckArxiv{"arXiv ID present?"}
    CheckS2{"S2 paperId present?"}
    Fingerprint["title + year hash<br/>fp:..."]

    Incoming --> CheckDOI
    CheckDOI -->|yes| IdDOI["paper_id = doi:..."]
    CheckDOI -->|no| CheckArxiv
    CheckArxiv -->|yes| IdArxiv["paper_id = arxiv:..."]
    CheckArxiv -->|no| CheckS2
    CheckS2 -->|yes| IdS2["paper_id = s2:..."]
    CheckS2 -->|no| Fingerprint

    IdDOI --> Merge
    IdArxiv --> Merge
    IdS2 --> Merge
    Fingerprint --> Merge

    Merge["Cross-source merge:<br/>same paper_id → one record<br/>sources = ss + arxiv"]
```

**Two dedupe stages:**
1. **Cross-source** (`merge_paper_records` in fetch): same `paper_id` within one fetch
2. **In-run pool** (`dedupe_papers` in agent): DOI → arXiv → title across rounds
3. **Persistent DB** (`upsert_papers_batch`): merge metadata on existing `paper_id`

---

## 5. Ranking: all metrics computed, one primary sorts

```mermaid
flowchart TD
    Input["query = rank_topic original user topic<br/>papers = title + abstract dicts"]
    Input --> SBERT["sbert_cosine<br/>all-MiniLM-L6-v2"]
    Input --> TFIDF["tfidf_cosine<br/>sklearn TfidfVectorizer"]
    Input --> Recency["recency<br/>year normalized in timeline"]

    SBERT --> Scores["scores dict per paper"]
    TFIDF --> Scores
    Recency --> Scores

    Scores --> Primary{"primary_method<br/>from survey_config"}
    Primary -->|sbert default| SortS["relevance_score = sbert_cosine"]
    Primary -->|tfidf| SortT["relevance_score = tfidf_cosine"]
    Primary -->|recency| SortR["relevance_score = recency"]

    SortS --> Sorted["sorted list descending"]
    SortT --> Sorted
    SortR --> Sorted
    Sorted --> Gate["quality gate uses relevance_score"]
```

**Primary method is NOT auto-selected at runtime.** It is configured (`data/survey_config.json` → `rank_method`) or overridden (`--rank-method` in eval). Robustness is studied offline by comparing target-hit rates across methods in `src/eval.py`.

---

## 6. Storage tiers

| Tier | Path | What it stores | Lifetime |
|------|------|----------------|----------|
| Source cache | `outputs/cache/semantic_scholar/`, `outputs/cache/arxiv/` | Raw API responses keyed by hash(endpoint + params) | Until deleted; `--no-cache` bypasses |
| Main papers DB | `outputs/papers.db` | Canonical deduped `PaperRecord` rows + `source_hits` | Grows across runs |
| Search history | `outputs/history.db` | Full web search session JSON (audit/replay) | 60-day retention |
| Run artifacts | `outputs/runs/{run_id}/` | `result.json`, `rounds.json`, `metrics.json` | Per live CLI/web search |
| Eval batch | `outputs/eval/{timestamp}.json` | Benchmark comparison rows | Per eval run |

---

## 7. Stage I/O reference

### 7.1 Semantic Scholar adapter

| | |
|---|---|
| **Input** | `query` (search string), `limit`, `offset`, optional `year`, `fieldsOfStudy` |
| **HTTP** | `GET api.semanticscholar.org/graph/v1/paper/search` |
| **Raw output** | JSON `{total, offset, data: [{paperId, title, authors, year, abstract, externalIds, ...}]}` |
| **Normalized output** | `PaperRecord` via `normalize_s2()` |
| **Cache key** | `sha256(source + url + sorted params)` |

### 7.2 arXiv adapter

| | |
|---|---|
| **Input** | `query` → wrapped as `all:{query}`, `start`, `max_results` |
| **HTTP** | `GET export.arxiv.org/api/query` |
| **Raw output** | Atom XML feed with `<entry>` elements |
| **Normalized output** | `PaperRecord` via `normalize_arxiv()` |
| **Rate limit** | ~3 seconds between requests (polite use) |

### 7.3 `fetch_all_sources()`

| | |
|---|---|
| **Input** | `query: str`, `SurveyConfig`, optional `offset`, `limit` |
| **Output** | `(list[PaperRecord], FetchStats)` where FetchStats has `api_calls`, `cache_hits`, `api_calls_by_source`, `fetch_errors` |
| **Cap** | `max_candidates_per_run` (default 200) |

### 7.4 `rank_papers()`

| | |
|---|---|
| **Input** | `query` (always **original rank_topic**), `papers` (agent dicts with title + abstract), `methods`, `primary_method`, year window |
| **Output** | Same papers + `scores: {sbert_cosine, tfidf_cosine, recency}`, `rank_method`, `relevance_score` (from primary), sorted descending |
| **Quality gate input** | Uses `relevance_score` only (primary method) |

### 7.5 `run_search_agent()`

| | |
|---|---|
| **Input** | `original_query`, `mode` (agent / single_fetch / multi_fetch_same), `refine`, optional `rank_method`, `survey_config` |
| **Output** | `{query, mode, papers[top 10], status, rounds[], metrics, search_queries_used, rank_topic, ...}` |
| **Status** | `ok`, `weak_results`, `partial_success`, `failure` |

---

## 8. Agent modes (research baselines)

| Mode | Fetches | Ollama | Max rounds | Research question |
|------|---------|--------|------------|-------------------|
| `single_fetch` | 1 query, 2 pages/source | No | 1 | Strong one-shot baseline |
| `multi_fetch_same` | Same query re-fetched | No | 3 | Does pagination alone help? |
| `agent` | Adaptive query rewrite | Yes | 3 | Does LLM query refinement help? |

**Invariant:** ranking always uses `rank_topic` (original user topic). Only the **search string** sent to APIs changes after Ollama refinement.

---

## 9. Quality gate thresholds (`src/config.py`)

| Rule | Threshold | Meaning |
|------|-----------|---------|
| `SCORE_TOP_MIN` | 0.35 | Best paper must clear this |
| `SCORE_GOOD` | 0.40 | "Strong match" count |
| `MIN_GOOD_PAPERS` | 3 | Need ≥3 papers ≥ 0.40 |
| `MIN_SCORE_GAP` | 0.08 | Top score must beat median-of-top-5 by this margin |

If gate fails and refinements remain → Ollama produces a new search query.

---

## 10. What changed since v2

| Area | v2 | v3 |
|------|----|----|
| Diagram scope | UI + agent loop | Full retrieval stack with I/O contracts |
| Ranking | "multi-metric" mention | Explicit primary vs auxiliary metrics |
| Storage | papers.db mentioned | Three-tier storage model documented |
| Dedupe | single step | Three dedupe stages named |
| Primary method | implicit | config + eval-driven, not runtime auto-pick |
