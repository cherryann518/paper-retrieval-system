# Paper Retrieval System — run notes

## Standard steps (web UI)

Run these in order. Use **two terminal tabs**: one for Flask, one optional for checks.

### 1. Project + venv

```bash
cd "/Users/cherryann/PLAINTEXT/Paper Retrieval System (w2-3)"
source .venv/bin/activate
pip install -r requirements.txt   # first time only
```

### 1b. Semantic Scholar API key (recommended)

Create a `.env` file in the project root (copy from `.env.example`):

```bash
cp .env.example .env
# Edit .env and set:
# SEMANTIC_SCHOLAR_API_KEY=your-key-here
```

Or export for the session:

```bash
export SEMANTIC_SCHOLAR_API_KEY="your-key-here"
```

With a key: **1 request/second** rate limit is enforced automatically. Do not commit `.env` to git.

### 2. Ollama (for query refinement when scores are weak)

Ollama must be running before searches that trigger the agent loop.

```bash
# Option A: open the Ollama Mac app (usually enough)

# Option B: terminal
ollama serve
```

Pull a model (see **Recommended models** below). Quick check:

```bash
ollama list
curl http://127.0.0.1:11434/api/tags
```

Tell the app which model to use (match a name from `ollama list`):

```bash
export OLLAMA_MODEL=qwen2.5-coder:7b   # OR
export OLLAMA_MODEL=llama3.2:3b      
```

### 3. Start the Flask server

```bash
python3 -m src.app
```

Open http://127.0.0.1:5000 — search from the browser.

Stop the server with `Ctrl+C`.

**Port 5000 in use?** Quit the other process, or change `port=` in `src/app.py` (e.g. `8080`).

---

## Standard steps (CLI)

Same Ollama + venv setup as above, then:

```bash
# Live: full agent (fetch → rank → refine if weak → return top 10)
python3 -m src.main "retrieval augmented generation"

# One-shot fetch, no Ollama refinement
python3 -m src.main "retrieval augmented generation" --mode single_fetch

# Re-fetch the same query up to 3 rounds (no Ollama) — ablation control
python3 -m src.main "retrieval augmented generation" --mode multi_fetch_same

# Agent loop but Ollama disabled
python3 -m src.main "retrieval augmented generation" --mode agent --no-refine

# Debug only: local sample papers, no API, no agent
python3 -m src.main --offline "retrieval augmented generation"
```

Every live CLI search writes run artifacts to `outputs/runs/{run_id}/`.

---

## Evaluation modes (`python -m src.eval`)

The eval script runs a **fixed benchmark** and compares retrieval strategies on the same queries. Use this to measure whether your agent (especially Ollama refinement) actually helps.

### Benchmark file

Default: `data/benchmark/queries.json`

Each entry:

```json
{
  "query": "why do antibiotics stop working over time",
  "category": "vague",
  "note": "Natural phrasing — optional",
  "targets": [
    {
      "title": "Antibiotic resistance threats in the United States",
      "doi": "10.15585/mmwr.su6303a1"
    }
  ]
}
```

- `query` — topic string passed to the agent
- `category` — `vague`, `short`, `short_acronym`, `casual`, or `control` (shown in eval table)
- `targets` — optional known papers (match by DOI, arXiv, or exact title)

The default benchmark mixes query types across **different fields** (biology, climate, neuroscience, social science, etc.):

| Category | Purpose | Example |
|----------|---------|---------|
| `short_acronym` | Ambiguous short token (no code expansion) | `CRISPR` |
| `short` | Brief topic phrase → often triggers Ollama | `coral bleaching` |
| `vague` | Natural-language questions → main agent test | `why do antibiotics stop working over time` |
| `control` | Keywords or exact titles → should work in one fetch | `hallmarks of cancer cell biology review` |
| `casual` | Broad topic, no target paper | `how cities can reduce air pollution` |

Each entry may include a `note` field explaining what that case is meant to test.

### The three modes

| Mode | What it does | Ollama? | Rounds | Use case |
|------|----------------|---------|--------|----------|
| **`single_fetch`** | One search query, one round, up to 2 paginated API pages | No | 1 | Baseline: "what if we only search once?" |
| **`multi_fetch_same`** | Same query every round, merge + re-rank (up to 3 rounds) | No | 3 | Control: "does fetching more pages help without smarter queries?" |
| **`agent`** | Full loop: fetch → rank → quality gate → Ollama rewrite if weak (up to 2 refinements) | Yes | up to 3 | Your system: adaptive query refinement |

All modes rank against the **original user topic** (never the rewritten search string).

**Fetch per round:** up to 100 papers × 2 pages = ~200 candidates before dedupe (`src/config.py`: `SEMANTIC_SCHOLAR_FETCH_LIMIT`, `MAX_PAGES_PER_QUERY`).

### Commands

```bash
# All three modes on the default benchmark (10 queries)
python -m src.eval

# Compare baseline vs agent only (faster)
python -m src.eval --modes single_fetch agent

# Custom benchmark path
python -m src.eval --benchmark data/benchmark/queries.json

# Save to a specific file
python -m src.eval --output outputs/eval/my_run.json
```

**Requirements:** Semantic Scholar API key in `.env`. For `agent` mode, Ollama must be running.

**Output:** Terminal summary table + JSON saved to `outputs/eval/{timestamp}.json`.

Example table columns:

```
query                            cat     mode              top  t10g tgt10 tgtP  ref     bΔ  api oll      ms status
coral bleaching                    short   single_fetch     0.380    2   0/1  1/1    0      -    2   0    2100 weak_results
coral bleaching                    short   agent            0.520    4   1/1  1/1    1 +0.140    4   1    8400 ok
```

- **top** — best `relevance_score` in the merged pool
- **t10g** — papers scoring ≥ 0.40 in the **returned top 10** (not the whole pool)
- **tgt10** — targets found in top 10 (e.g. `1/1`)
- **tgtP** — targets found anywhere in the ranked pool (shows “fetched but ranked low”)
- **ref** — refinement rounds completed
- **bΔ** — change in `batch_top_score` from round 0 to last round (did the new fetch help?)
- **api** / **oll** — call counts
- **status** — `ok`, `weak_results`, `partial_success`, or `failure`

After the table, eval prints an **Agent vs single_fetch** summary per query (winner + short note).

### How to read results (does refinement help?)

Compare **`single_fetch`** vs **`agent`** on the same query (or read the auto summary at the bottom):

- **Agent wins** when: higher `top` or `t10g`, `tgt10` improves, or `weak_results` → `ok` with `oll > 0`
- **Refinement never ran** when: round 0 already passed the gate (`oll = 0`) — common on `control` queries
- **tgtP > tgt10** means the paper was fetched but ranked outside top 10 — ranking problem, not fetch problem
- **bΔ > 0** means the refined query’s fetch scored better than round 0’s fetch alone

---

## Run artifacts

Every live search (CLI and web) saves JSON under `outputs/runs/{run_id}/`:

| File | Contents |
|------|----------|
| `result.json` | Full response: papers, status, rounds, metrics |
| `rounds.json` | Per-round telemetry only |
| `metrics.json` | Summary: latency, api_calls, ollama_calls, top_score, etc. |

Eval results (multi-query batch runs) go to `outputs/eval/` instead.

---

## Recommended Ollama models

Query refinement only needs a **short search string** — a small general model is enough.

| Model | Pull command | Notes |
|-------|----------------|-------|
| **llama3.2:3b** | `ollama pull llama3.2:3b` | Best default: fast, low RAM, good at short instructions |
| **qwen2.5:7b** | `ollama pull qwen2.5:7b` | Strong general model if you have ~8GB+ RAM |
| **phi3:mini** | `ollama pull phi3:mini` | Very light option |

**Your current model (`qwen2.5-coder:7b`):** works fine — set `export OLLAMA_MODEL=qwen2.5-coder:7b`. Coder models are tuned for code, not academic search, so results may be slightly less consistent than `llama3.2:3b` or `qwen2.5:7b` for this task. No need to download another model unless refinement quality feels off.

Default in code is `llama3.2` (full 3B tag). Override with `OLLAMA_MODEL` if you use something else.

---

## What you'll see in the Flask terminal

```
[search] query='...' source=live
[agent] round=0 search_query='...'
[agent] acceptable=False reason=top_score_low (0.310 < 0.35)
[agent] refined query='dense passage retrieval neural'
[agent] round=1 search_query='dense passage retrieval neural'
[agent] acceptable=True reason=ok
[search] retrieved 10 papers status=ok
[search] top result: ... (score=0.6454)
[search] done in 12.3s
[artifacts] saved run 20250619T143022 → outputs/runs/20250619T143022
```

**Status values:**

| Status | Meaning |
|--------|---------|
| `ok` | Quality gate passed |
| `weak_results` | Finished but scores still below threshold |
| `partial_success` | Got papers, but some API calls failed or Ollama was unavailable |
| `failure` | No papers retrieved at all |
| `offline` | Sample papers mode |

**Fail-soft:** A failed Semantic Scholar page no longer kills the whole search. You'll see `[agent] fetch failed query=... page=...` in the terminal; partial results are still returned when possible.

If Ollama is down: search still returns results; `[agent] Ollama unavailable: ...` and status is usually `partial_success` or `weak_results`.

---

## Copy-paste snippets

**Offline sample papers (debug):**
```bash
cd "/Users/cherryann/PLAINTEXT/Paper Retrieval System (w2-3)"
source .venv/bin/activate

python3 -c "
from src.tools import load_sample_papers

for p in load_sample_papers():
    print('Title:', p['title'])
    print('Authors:', ', '.join(p['authors']))
    print('Year:', p['year'])
    print('Abstract:', p['abstract'][:300], '...\n')
"
```

**Live Semantic Scholar only (no agent):**
```bash
python3 -c "
from src.tools import search_semantic_scholar, SemanticScholarError

try:
    papers = search_semantic_scholar('large language models', limit=3)
    for p in papers:
        print('Title:', p['title'])
        print('Abstract:', (p['abstract'] or '')[:300], '...\n')
except SemanticScholarError as e:
    print('Failed:', e)
"
```

**Web API offline (curl debug):**
```bash
curl -X POST http://127.0.0.1:5000/search \
  -H "Content-Type: application/json" \
  -d '{"query":"retrieval augmented generation","offline":true}'
```

---

## Quick reference

| Mode | Command |
|------|---------|
| Web (live) | `python3 -m src.app` → http://127.0.0.1:5000 |
| CLI (full agent) | `python3 -m src.main "your topic"` |
| CLI (single fetch) | `python3 -m src.main "your topic" --mode single_fetch` |
| CLI (multi fetch, no LLM) | `python3 -m src.main "your topic" --mode multi_fetch_same` |
| CLI (offline debug) | `python3 -m src.main --offline "your topic"` |
| Benchmark eval (all modes) | `python -m src.eval` |
| Benchmark eval (subset) | `python -m src.eval --modes single_fetch agent` |

Live mode uses Semantic Scholar only — **no silent fallback** to sample data in normal search. Offline mode (`--offline` or `"offline": true` in POST body) uses `data/sample_papers.json` only.

**Config knobs** (`src/config.py`): fetch limit (100/page), pages per query (2), top-N returned (10), max refinement rounds (2), score thresholds.
