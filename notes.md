# Paper Retrieval System — run notes

## Standard steps (web UI)

Run these in order. Use **two terminal tabs**: one for Flask, one optional for checks.

### 1. Project + venv

```bash
cd "/Users/cherryann/Documents/PLAINTEXT/Paper Retrieval System (w2-3)"
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
# Live: Semantic Scholar + agent + Ollama refinement when needed
python3 -m src.main "retrieval augmented generation"

# Debug only: local sample papers, no API, no agent
python3 -m src.main --offline "retrieval augmented generation"
```

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
[agent] acceptable=False reason=...
[agent] refined query='...'
[search] retrieved 8 papers status=ok
[search] top result: ... (score=0.6454)
[search] done in 12.3s
```

If Semantic Scholar fails: red error box in the browser + `[search] API error: ...` in terminal.

If Ollama is down: search still returns results; you'll see `[agent] Ollama unavailable: ...` and `status=weak_results`.

---

## Copy-paste snippets

**Offline sample papers (debug):**
```bash
cd "/Users/cherryann/Documents/PLAINTEXT/Paper Retrieval System (w2-3)"
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
| CLI (live) | `python3 -m src.main "your topic"` |
| CLI (offline debug) | `python3 -m src.main --offline "your topic"` |

Live mode uses Semantic Scholar only — **no silent fallback** to sample data. API errors show in the UI.
