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
