# AI Web Agent

Local web research agent built with FastAPI, Playwright, and Ollama.

## What it does

1. Accepts a natural-language request from the user
2. Uses Ollama to classify the request and extract the search keyword
3. Discovers relevant sites from live search results
4. Ranks those sites into primary and fallback candidates
5. Scrapes the pages with Playwright
6. Uses Ollama again to extract structured answers from the scraped text

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

The app expects Ollama at `http://localhost:11434`.

## Run

```powershell
py -3 -m uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`.

## Quick test

```powershell
py -3 test_scraper.py
```
