# Pipeline flowchart v1

Current system: search → score → optionally refine query with Ollama → show ranked papers.

```mermaid
flowchart TD
    subgraph INPUT["User input"]
        Q1["Type a research topic<br/><small>`python3 -m src.main`</small>"]
        Q2["Search in the browser<br/><small>`POST /search`</small>"]
    end

    subgraph ENTRY["Start the app"]
        MAIN["Command-line interface<br/><small>`src/main.py`</small>"]
        APP["Web server<br/><small>`src/app.py`</small>"]
    end

    MODE{{"Debug with<br/>sample papers?"}}

    subgraph OFFLINE["Offline path"]
        LOAD["Load local sample papers<br/><small>`load_sample_papers()`</small>"]
        RANK_OFF["Rank by relevance<br/><small>`embed_and_rank()`</small>"]
    end

    subgraph AGENT["Search agent"]
        direction TB
        START["Keep original topic,<br/>start search query<br/><small>`run_search_agent()`</small>"]
        FETCH["Fetch papers from Semantic Scholar<br/><small>`search_semantic_scholar()`</small>"]
        MERGE["Merge new papers, remove duplicates<br/><small>`dedupe_papers()`</small>"]
        SCORE["Score papers against original topic<br/><small>`embed_and_rank()`</small>"]
        CHECK{{"Good enough<br/>results?"}}
        RULES["Top score, count of strong matches,<br/>score spread<br/><small>`results_acceptable()`</small>"]
        RETRY{{"Retries left?<br/><small>max 2</small>"}}
        REFINE["Ask Ollama for a better search query<br/><small>`ollama_refine_query()`</small>"]
        OK["Return confident results<br/><small>`status: ok`</small>"]
        WEAK["Return best available results<br/><small>`status: weak_results`</small>"]
    end

    subgraph ERRORS["When something fails"]
        API_FAIL["API error shown to user<br/><small>`SemanticScholarError` → 503</small>"]
        OLLAMA_FAIL["Skip refinement, use current papers<br/><small>`OllamaError`</small>"]
    end

    subgraph OUTPUT["Show results"]
        CLI_OUT["Print paper list in terminal"]
        WEB_OUT["Paper cards in browser<br/><small>`static/index.html`</small>"]
    end

    Q1 --> MAIN
    Q2 --> APP
    MAIN --> MODE
    APP --> MODE

    MODE -->|"yes — `--offline`"| LOAD
    LOAD --> RANK_OFF
    RANK_OFF --> CLI_OUT
    RANK_OFF --> WEB_OUT

    MODE -->|"no — live"| START
    MAIN --> START

    START --> FETCH
    FETCH -->|"rate limit / network"| API_FAIL
    API_FAIL --> WEB_OUT
    FETCH --> MERGE --> SCORE --> CHECK
    CHECK --> RULES
    CHECK -->|"yes"| OK
    OK --> CLI_OUT
    OK --> WEB_OUT

    CHECK -->|"no"| RETRY
    RETRY -->|"yes"| REFINE
    REFINE -->|"Ollama not running"| OLLAMA_FAIL
    OLLAMA_FAIL --> WEAK
    REFINE -->|"new query"| FETCH
    RETRY -->|"no"| WEAK
    WEAK --> CLI_OUT
    WEAK --> WEB_OUT

    style START fill:#e8f4ea
    style FETCH fill:#e8f4ea
    style MERGE fill:#e8f4ea
    style SCORE fill:#e8f4ea
    style CHECK fill:#e8f4ea
    style RULES fill:#e8f4ea
    style REFINE fill:#e8f4ea
    style OK fill:#e8f4ea
    style MAIN fill:#e8f4ea
    style APP fill:#e8f4ea
    style CLI_OUT fill:#e8f4ea
    style WEB_OUT fill:#e8f4ea
    style LOAD fill:#fff8e6
    style RANK_OFF fill:#fff8e6
    style WEAK fill:#fff8e6
    style API_FAIL fill:#fdecea
    style OLLAMA_FAIL fill:#fff8e6
```

## In plain English

1. **User** enters a topic via the terminal or web UI.
2. **Live path (default):** the agent searches Semantic Scholar, pools papers across attempts, and scores them against the **original** topic.
3. **Quality check:** if scores pass thresholds, return results. If not, Ollama suggests a refined search query (up to 2 times).
4. **Offline path:** only for debugging — loads `data/sample_papers.json`, no API, no agent loop.
5. **Errors:** API failures stop with an error message; Ollama failures skip refinement and return the best papers found so far.

## Agent loop

```
original topic (never changes)
    ↓
search online → merge & dedupe → score against original topic
    ↓
good enough? → yes → done
    ↓ no
Ollama rewrites search query → search again (max 2 rounds)
    ↓
return best ranked papers (top 8)
```
