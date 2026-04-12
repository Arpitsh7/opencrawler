from __future__ import annotations

import asyncio
import os
import re
import sys
import urllib.parse
from contextlib import asynccontextmanager

# Playwright's async API spawns a subprocess for the browser driver. On Windows the
# default asyncio loop (SelectorEventLoop) does not implement subprocess support and
# raises NotImplementedError; ProactorEventLoop does.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ai_extractor import extract_structured
from config import get_settings
from content_window import select_relevant_excerpt
from multi_scraper import scrape_all
from parallel_scrape import scrape_all_async
from site_selector import select_sites

templates = Jinja2Templates(directory="templates")
MOJIBAKE_REPLACEMENTS = {
    "â‚¹": "₹",
    "â€”": " - ",
    "â€“": " - ",
    "â€˜": "'",
    "â€™": "'",
    "â€œ": '"',
    "â€": '"',
}

class AgentRequest(BaseModel):
    request: str


def clean_text(value: str) -> str:
    cleaned = value
    for wrong, right in MOJIBAKE_REPLACEMENTS.items():
        cleaned = cleaned.replace(wrong, right)
    return cleaned


def normalize_site_label(value: str) -> str:
    cleaned = clean_text(value).strip()
    cleaned = re.sub(r"^\*+|\*+$", "", cleaned).strip()
    cleaned = re.sub(r"^\[|\]$", "", cleaned).strip()
    return cleaned


def summarize_error(value: str) -> str:
    text = clean_text(value or "").strip()
    if not text:
        return ""

    lowered = text.lower()
    if "timeout" in lowered:
        return "timeout"
    if "temporary_error" in lowered:
        return "temporary_error"
    if "blocked" in lowered or "access denied" in lowered:
        return "blocked"
    if "too_short" in lowered:
        return "too_short"
    if "page not found" in lowered or "not found" in lowered:
        return "not_found"

    first_line = text.splitlines()[0].strip()
    return first_line[:80]


def split_summary_into_items(summary: str) -> tuple[str, list[str]]:
    cleaned = clean_text(summary).strip()
    if not cleaned:
        return "", []

    parts = [part.strip() for part in re.split(r"\s+\*\s+", cleaned.lstrip("* ").strip()) if part.strip()]
    if len(parts) > 1:
        return "", parts

    return cleaned, []


def is_no_data_text(value: str) -> bool:
    normalized = clean_text(value or "").strip().lower()
    normalized = re.sub(r"^[\-\*\u2022\.\s]+", "", normalized).strip()
    return normalized in {
        "no data found",
        "no relevant data found",
        "no specific data found",
        "no prices mentioned",
        "no specific price mentioned",
    }


def consolidate_sections(sections: list[dict]) -> list[dict]:
    filtered_sections = []
    for section in sections:
        summary = clean_text(section.get("summary", "")).strip()
        items = [clean_text(item).strip() for item in section.get("items", []) if clean_text(item).strip()]
        if not items and "*" in summary:
            summary, inferred_items = split_summary_into_items(summary)
            items.extend(inferred_items)
        items = [item for item in items if not is_no_data_text(item)]
        if is_no_data_text(summary):
            continue
        if not summary and not items:
            continue
        filtered_sections.append(
            {
                "site": normalize_site_label(section.get("site", "")),
                "summary": summary,
                "items": items,
            }
        )

    return filtered_sections


def parse_extracted_sections(extracted_text: str) -> list[dict]:
    sections = []
    current = None

    for raw_line in clean_text(extracted_text).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        header_match = re.match(r"^\[?([^\]]+?)\]?\s*:\s*(.*)$", line)
        if header_match and (
            "." in header_match.group(1) or header_match.group(1).lower().startswith("site")
        ):
            if current:
                sections.append(current)
            detail = header_match.group(2).strip()
            current = {
                "site": normalize_site_label(header_match.group(1)),
                "summary": detail if detail and not detail.startswith("-") else "",
                "items": [],
            }
            if detail.startswith("-"):
                current["items"].append(detail[1:].strip())
            continue

        if current is None:
            continue

        if line.startswith("-"):
            current["items"].append(line[1:].strip())
        elif current["summary"]:
            current["summary"] += " " + line
        else:
            current["summary"] = line

    if current:
        sections.append(current)

    return consolidate_sections(sections)


def build_source_by_host(urls: list[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for url in urls:
        try:
            host = urllib.parse.urlparse(url).netloc.lower()
        except Exception:
            continue
        if not host:
            continue
        bare = host[4:] if host.startswith("www.") else host
        index[host] = url
        index[bare] = url
    return index


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def use_shared_async_browser() -> bool:
    """
    Shared async Playwright often breaks on Windows under uvicorn (reload / event loop).
    Default: off on win32, on elsewhere. Override with USE_ASYNC_PLAYWRIGHT=1 or
    FORCE_SUBPROCESS_SCRAPER=1.
    """
    if _env_truthy("FORCE_SUBPROCESS_SCRAPER"):
        return False
    if sys.platform == "win32" and not _env_truthy("USE_ASYNC_PLAYWRIGHT"):
        return False
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.browser = None
    app.state.scraper_mode = "subprocess"

    if not use_shared_async_browser():
        if sys.platform == "win32" and not _env_truthy("USE_ASYNC_PLAYWRIGHT"):
            print("Windows: using subprocess Playwright (scraper.py per URL). Set USE_ASYNC_PLAYWRIGHT=1 to try shared async browser.")
        yield
        return

    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            app.state.browser = browser
            app.state.scraper_mode = "shared_async"
            yield
            await browser.close()
    except Exception as exc:
        print(f"Shared async browser failed ({type(exc).__name__}: {exc}); using subprocess Playwright.")
        app.state.browser = None
        app.state.scraper_mode = "subprocess"
        yield


app = FastAPI(lifespan=lifespan)

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health(request: Request):
    browser = getattr(request.app.state, "browser", None)
    mode = getattr(request.app.state, "scraper_mode", "subprocess")
    return {
        "status": "ok",
        "browser_ready": browser is not None,
        "scraper_mode": mode,
    }

@app.post("/agent")
async def agent(request: Request, data: AgentRequest):
    try:
        loop = asyncio.get_running_loop()
        settings = get_settings()

        sites = await loop.run_in_executor(None, select_sites, data.request)
        print(
            f"Category={sites['category']} Keyword={sites['keyword']} "
            f"Queries={sites.get('queries', [])}"
        )
        print(f"Primary sites: {sites['primary']}")
        print(f"Fallback sites: {sites['fallback']}")

        browser = getattr(request.app.state, "browser", None)
        if browser is None:
            scraped = await loop.run_in_executor(None, scrape_all, sites)
        else:
            scraped = await scrape_all_async(browser, sites, settings)

        combined_text = ""
        successful_sites = []
        scrape_summary = []

        for r in scraped:
            scrape_summary.append(
                {
                    "url": r["url"],
                    "status": r["status"],
                    "error": summarize_error(r.get("error", "")),
                    "text_length": len(r.get("text", "")),
                }
            )
            if r["status"] == "ok" and r["text"]:
                try:
                    hostname = urllib.parse.urlparse(r["url"]).netloc or r["url"]
                except Exception:
                    hostname = r["url"]
                excerpt = select_relevant_excerpt(
                    r["text"],
                    sites["keyword"],
                    sites["category"],
                    settings.max_chars_per_source,
                )
                combined_text += f"\n\n--- SOURCE: {hostname} ---\n{excerpt}"
                successful_sites.append(r["url"])

        if not combined_text:
            return {
                "status": "error",
                "message": "All sites blocked or returned no data. Try a different request.",
                "debug": {
                    "category": sites["category"],
                    "keyword": sites["keyword"],
                    "queries": sites.get("queries", []),
                    "primary": sites["primary"],
                    "fallback": sites["fallback"],
                    "scrape_summary": scrape_summary,
                },
            }

        print(f"Sending {len(successful_sites)} pages to Ollama (extraction)...")

        def run_extract():
            return extract_structured(combined_text, data.request, successful_sites, settings)

        raw_out, json_sections, extraction_mode = await loop.run_in_executor(None, run_extract)
        result = clean_text(raw_out)
        if json_sections is not None:
            result_sections = consolidate_sections(json_sections)
        else:
            result_sections = parse_extracted_sections(result)

        source_by_host = build_source_by_host(successful_sites)

        return {
            "status": "success",
            "sites_scraped": successful_sites,
            "source_by_host": source_by_host,
            "extraction_mode": extraction_mode,
            "visible_source_count": len(result_sections),
            "category": sites["category"],
            "keyword": sites["keyword"],
            "extracted": result,
            "result_sections": result_sections,
            "debug": {
                "queries": sites.get("queries", []),
                "primary": sites["primary"],
                "fallback": sites["fallback"],
                "scrape_summary": scrape_summary,
            },
        }

    except Exception as e:
        import traceback

        traceback.print_exc()
        return {"status": "error", "message": str(e)}
