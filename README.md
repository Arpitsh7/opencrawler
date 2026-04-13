# AI Web Agent

Local web research agent built with FastAPI, Playwright, and Ollama.

## What it does

1. Accepts a natural-language request from the user
2. Uses Ollama to classify the request and extract the search keyword
3. Discovers relevant sites from live search results
4. Ranks those sites into primary and fallback candidates
5. Scrapes the pages with **one shared Chromium** (async Playwright, configurable concurrency) instead of spawning a new browser per URL
6. **Keyword-aware excerpts** trim each page to the most relevant window before sending text to the model (full scrape is still used for validation)
7. Uses Ollama again to extract answers, preferring **JSON** output when the server supports it, with **plain-text fallback** for older Ollama builds
8. Returns a **`source_by_host` map** so the UI can link each card to the exact URL that was scraped

## Complete tech stack used

### Core runtime

- **Python 3.10+**: main application language
- **FastAPI**: API server and app lifecycle management
- **Uvicorn**: ASGI server for local development
- **Jinja2**: template rendering for the frontend page

### AI / LLM layer

- **Ollama** (local): runs the model used by the agent pipeline
- **Llama 3** (default model): request classification, keyword extraction, and answer extraction
- **Structured JSON extraction + fallback text extraction**: ensures compatibility across different Ollama/server capabilities

### Web discovery and scraping

- **DuckDuckGo HTML search parsing**: initial URL discovery for query-specific candidates
- **Playwright (Chromium)**: browser automation for scraping pages
- **Async shared-browser scraping** (`scraper_async.py`, `parallel_scrape.py`): higher-throughput mode with one browser and parallel contexts
- **Subprocess scraper fallback** (`scraper.py`, `multi_scraper.py`): robust per-URL scraping path, especially useful on Windows
- **BeautifulSoup4**: parsing search result pages and extracting candidate links
- **Requests**: HTTP calls for search discovery and auxiliary fetch operations

### Ranking, filtering, and quality layers

- **Site ranking + source selection** (`site_selector.py`): primary vs fallback queues
- **Content windowing** (`content_window.py`): keyword-aware excerpt selection from long page text
- **Trace error normalization** (`trace_format.py`): short, UI-friendly scrape diagnostics
- **Post-extraction cleanup** (`main.py`): category-aware polishing and fallback section completion

### Frontend / UX

- **Server-rendered HTML/CSS/JS** (`templates/index.html`)
- **Interactive research dashboard**: pipeline steps, source cards, and trace blocks
- **Debug/trace visibility**: queries used, source queues, scrape outcomes, and status state

### Configuration and operations

- **Environment-variable based settings** (`config.py`)
- **Health endpoint** (`/health`): runtime mode and browser readiness checks
- **Local test script** (`test_scraper.py`) for scraper sanity checks

## Step-by-step: how ScrapeX works

### 1) User request intake

The user submits a natural language query through the UI (for example, product prices, specs, news, jobs, or quotes).  
`main.py` receives this in the `/agent` endpoint.

### 2) Query understanding and intent classification

The app calls Ollama to:
- detect category (such as `prices`, `tech_specs`, `news`, `jobs`, `quotes`)
- extract a strong keyword phrase
- generate search-ready query variants

### 3) Live source discovery

`search_engine.py` fetches search result candidates (DuckDuckGo), then `site_selector.py` ranks and organizes URLs into:
- **Primary queue** (best expected signal)
- **Fallback queue** (backup sources if primaries fail/underperform)

### 4) Scraping execution

Depending on platform/runtime settings:
- **Async shared-browser mode** (`scraper_async.py` + `parallel_scrape.py`), or
- **Subprocess mode** (`multi_scraper.py` invoking `scraper.py`)

The scraper validates page quality, follows listing/detail links where needed, handles dynamic pages, and filters weak/blocked/no-result pages.

### 5) Relevance-focused text preparation

`content_window.py` trims each scraped page into a high-signal excerpt based on the detected query/category while keeping scrape validation separate from LLM context trimming.

### 6) AI extraction and structuring

`ai_extractor.py` sends prepared page content to Ollama:
- tries strict **JSON** output first
- falls back to plain text extraction if needed

The response is normalized into source-wise result sections.

### 7) Output polishing and gap filling

`main.py` performs post-processing:
- category-aware cleanup of weak/junk lines
- augmentation when a successfully scraped host is missing from model output
- generation of `source_by_host` mapping for reliable source links in UI

### 8) Final UI response + trace

The frontend renders:
- result cards per source
- summary tiles (category/keyword/source count)
- trace panels (queries, primary/fallback queues, scrape outcomes)

This makes the output both useful for end users and debuggable for development.

## Configuration

Environment variables (all optional):

| Variable | Default | Purpose |
|----------|---------|---------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API base |
| `OLLAMA_MODEL` | `llama3` | Model for classification, keywords, and extraction |
| `OLLAMA_TIMEOUT_S` | `180` | Timeout for extraction calls |
| `OLLAMA_KEYWORD_TIMEOUT_S` | `45` | Timeout for short classification/keyword calls |
| `SCRAPE_CONCURRENCY` | `4` | Parallel Playwright contexts per request |
| `SCRAPE_TIMEOUT_MS` | `28000` | Navigation timeout per page |
| `SCRAPE_WAIT_MS` | `1200` | Extra wait after load for dynamic content |
| `MAX_CHARS_PER_SOURCE` | `5200` | Max characters per source passed to the LLM (after smart trimming) |
| `SEARCH_URLS_PER_DOMAIN` | `2` | DuckDuckGo results: allow more than one URL per domain |
| `SEARCH_MAX_RESULTS_PER_QUERY` | `12` | Cap on collected links per search query |
| `USE_ASYNC_PLAYWRIGHT` | (off on Windows) | Set to `1` to try shared async browser on Windows |
| `FORCE_SUBPROCESS_SCRAPER` | (off) | Set to `1` to always use `scraper.py` subprocesses |

## Setup

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -3 -m pip install -r requirements.txt
py -3 -m playwright install chromium
```

## Ollama

Make sure Ollama is running locally:

```powershell
ollama serve
ollama pull llama3
```

Override the base URL and model with `OLLAMA_BASE_URL` and `OLLAMA_MODEL` if needed.

## Run

```powershell
py -3 -m uvicorn main:app --reload
```

On **Windows**, the app **does not** start a shared async Playwright browser by default (Uvicorn’s event loop / `--reload` often breaks `asyncio.create_subprocess_exec`). It uses the **subprocess** scraper (`scraper.py` per URL) instead, which is reliable. To experiment with the faster shared async pool on Windows, set **`USE_ASYNC_PLAYWRIGHT=1`**. To force subprocess mode on any OS, set **`FORCE_SUBPROCESS_SCRAPER=1`**.

`main.py` still sets `WindowsProactorEventLoopPolicy` for other asyncio subprocess use.

Open `http://127.0.0.1:8000`. Health check: `http://127.0.0.1:8000/health`.

## Quick test

```powershell
py -3 test_scraper.py
```
