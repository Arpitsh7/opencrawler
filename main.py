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
from trace_format import format_scrape_error

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
    return format_scrape_error(clean_text(value or ""))


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


def _host_bare_from_url(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""
    if not host:
        return ""
    return host[4:] if host.startswith("www.") else host


def parse_source_excerpts(combined_text: str) -> dict[str, str]:
    """Map bare hostname (no www.) to excerpt for each --- SOURCE: --- block."""
    out: dict[str, str] = {}
    if not combined_text:
        return out
    pattern = re.compile(r"--- SOURCE:\s*(.+?)\s*---\s*\n(.*?)(?=\n\n--- SOURCE:|\Z)", re.DOTALL)
    for m in pattern.finditer(combined_text):
        raw_host = (m.group(1) or "").strip()
        body = (m.group(2) or "").strip()
        key = raw_host.lower()
        if key.startswith("www."):
            key = key[4:]
        if key:
            out[key] = body
    return out


def _keyword_terms(keyword: str, compare_targets: list[str]) -> list[str]:
    words: list[str] = []
    for value in [keyword, *compare_targets]:
        words.extend(re.findall(r"[a-z0-9]+", (value or "").lower()))
    # Keep meaningful tokens, dedupe while preserving order.
    seen = set()
    terms = []
    for w in words:
        if len(w) < 3:
            continue
        if w in seen:
            continue
        seen.add(w)
        terms.append(w)
    return terms


def _line_has_price_signal(line: str) -> bool:
    low = line.lower()
    return "₹" in line or "rs." in low or "inr" in low or ("price" in low and any(ch.isdigit() for ch in line))


def _line_has_model_signal(line: str, terms: list[str]) -> bool:
    low = line.lower()
    overlap = sum(1 for t in terms if t in low)
    if overlap >= 1:
        return True
    # Generic model/SKU-like token: letter+digits (works across domains, not brand-specific).
    if re.search(r"\b[a-z]{1,8}\d{1,5}[a-z0-9\-]*\b", low):
        return True
    # Generic named item pattern: at least 2 words and a number/spec hint.
    words = re.findall(r"[a-z0-9]+", low)
    has_spec_hint = any(sig in low for sig in ["ram", "storage", "battery", "processor", "chipset", "display", "camera"])
    return len(words) >= 2 and (has_spec_hint or any(ch.isdigit() for ch in low))


def heuristic_price_lines(
    text: str,
    keyword: str = "",
    compare_targets: list[str] | None = None,
    limit: int = 3,
) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    terms = _keyword_terms(keyword, compare_targets or [])
    items: list[str] = []

    for idx, line in enumerate(lines):
        if len(line) > 360:
            continue
        if _JUNK_PRICE_BULLET.search(line):
            continue

        has_price = _line_has_price_signal(line)
        has_model = _line_has_model_signal(line, terms)

        if has_price and has_model:
            items.append(line)
        elif has_price:
            # Try to attach nearby model context so we avoid bare amount rows.
            prev_line = lines[idx - 1].strip() if idx > 0 else ""
            if prev_line and len(prev_line) <= 220 and _line_has_model_signal(prev_line, terms):
                items.append(f"{prev_line} — {line}")
            else:
                items.append(line)
        elif has_model and any(sig in line.lower() for sig in ["ram", "storage", "battery", "processor", "chipset"]):
            # Sometimes price is omitted in one line, but spec line is still useful.
            items.append(line)

        if len(items) >= limit:
            break

    # Dedupe while preserving order.
    deduped: list[str] = []
    seen = set()
    for item in items:
        k = item.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(item)
    return deduped[:limit]


_JUNK_PRICE_BULLET = re.compile(
    r"protect\s*promise|convenience\s*fee|^\+\s*₹|no\s+cost\s+emi\b|emi\s+starting",
    re.IGNORECASE,
)


def _is_price_only_fragment(line: str) -> bool:
    """True if line looks like a bare amount / accessory with almost no product words."""
    s = (line or "").strip()
    if len(s) < 4:
        return True
    if _JUNK_PRICE_BULLET.search(s):
        return True
    letters = sum(1 for c in s if c.isalpha())
    if letters >= 14:
        return False
    low = s.lower()
    # Non-hardcoded model detector: token with letters+digits usually indicates SKU/model.
    if re.search(r"\b[a-z]{1,10}\d{1,6}[a-z0-9\-]*\b", low):
        return False
    if any(term in low for term in ["gb", "tb", "mah", "mp", "hz", "inch", "cm", "mm"]):
        return False
    if "₹" in s or "rs." in low:
        return letters < 8
    return False


def polish_price_results(
    sections: list[dict],
    category: str,
    compare_targets: list[str],
) -> list[dict]:
    """Remove fee/noise bullets; for compare queries, drop bare price-only lines when richer lines exist."""
    if category != "prices":
        return sections
    targets = list(compare_targets or [])
    out: list[dict] = []
    for sec in sections:
        raw_items = [clean_text(x).strip() for x in (sec.get("items") or []) if clean_text(x).strip()]
        after_junk = [it for it in raw_items if not _JUNK_PRICE_BULLET.search(it)]
        items = after_junk
        if len(targets) >= 2:
            richer = [it for it in after_junk if not _is_price_only_fragment(it)]
            if richer:
                items = richer
        summary = clean_text(sec.get("summary", "")).strip()
        if not items and not summary:
            continue
        out.append({**sec, "items": items, "summary": summary})
    return out


def polish_results_by_category(
    sections: list[dict],
    category: str,
    keyword: str = "",
    compare_targets: list[str] | None = None,
) -> list[dict]:
    """Category-aware cleanup without product hardcoding."""
    compare_targets = compare_targets or []
    keyword_terms = _keyword_terms(keyword, compare_targets)
    out: list[dict] = []

    for sec in sections:
        summary = clean_text(sec.get("summary", "")).strip()
        raw_items = [clean_text(x).strip() for x in (sec.get("items") or []) if clean_text(x).strip()]

        if category == "prices":
            raw_items = [it for it in raw_items if not _JUNK_PRICE_BULLET.search(it)]
            richer = [it for it in raw_items if not _is_price_only_fragment(it)]
            if len(compare_targets) >= 2 and richer:
                raw_items = richer
            # Prefer lines tied to query terms when we have enough choices
            if len(raw_items) > 3 and keyword_terms:
                scored = sorted(
                    raw_items,
                    key=lambda it: sum(1 for t in keyword_terms if t in it.lower()),
                    reverse=True,
                )
                raw_items = scored[:3]

        elif category == "tech_specs":
            keep_tokens = ["display", "battery", "camera", "ram", "storage", "processor", "chipset", "os"]
            filtered = [it for it in raw_items if any(tok in it.lower() for tok in keep_tokens)]
            if filtered:
                raw_items = filtered[:3]
            else:
                raw_items = raw_items[:3]

        elif category == "news":
            # Keep short factual lines; drop boilerplate.
            boilerplate = ("subscribe", "cookie", "sign in", "advertisement")
            filtered = [it for it in raw_items if not any(b in it.lower() for b in boilerplate)]
            raw_items = filtered[:3]

        elif category == "jobs":
            # Prefer lines with role/company/location-like tokens.
            job_markers = ["engineer", "developer", "analyst", "manager", "remote", "full-time", "intern"]
            filtered = [it for it in raw_items if any(m in it.lower() for m in job_markers)]
            raw_items = (filtered or raw_items)[:3]

        elif category == "quotes":
            # Quotes should be short and clean.
            raw_items = [it.strip(' -"\'') for it in raw_items if 8 <= len(it) <= 220][:3]

        # Generic dedupe
        deduped: list[str] = []
        seen = set()
        for it in raw_items:
            k = it.lower()
            if k in seen:
                continue
            seen.add(k)
            deduped.append(it)

        if not deduped and not summary:
            continue
        out.append({**sec, "summary": summary, "items": deduped[:3]})

    return out


def augment_sections_for_missing_scrapes(
    sections: list[dict],
    successful_urls: list[str],
    combined_text: str,
    category: str,
    keyword: str = "",
    compare_targets: list[str] | None = None,
) -> list[dict]:
    """
    The LLM often returns fewer sources than pages we actually scraped.
    Add one section per missing host so the UI matches successful scrapes.
    """
    excerpts = parse_source_excerpts(combined_text)
    covered: set[str] = set()
    for sec in sections:
        site = normalize_site_label(sec.get("site", "")).lower().replace("www.", "")
        if site:
            covered.add(site)

    augmented = list(sections)
    for url in successful_urls:
        key = _host_bare_from_url(url)
        if not key or key in covered:
            continue
        body = excerpts.get(key, "")
        items: list[str] = []
        if category == "prices" and body:
            items = heuristic_price_lines(body, keyword, compare_targets)
        summary = ""
        if not items:
            summary = (
                "The model did not return bullets for this source, but the page was scraped successfully. "
                "Open the link or use “Show raw output” for the full excerpt."
            )
        augmented.append({"site": key, "summary": summary, "items": items})
        covered.add(key)

    return augmented


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


@app.get("/app")
async def app_page(request: Request):
    return templates.TemplateResponse("app.html", {"request": request})


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
            return extract_structured(
                combined_text,
                data.request,
                successful_sites,
                settings,
                {
                    "category": sites.get("category", ""),
                    "keyword": sites.get("keyword", ""),
                    "compare_targets": sites.get("compare_targets") or [],
                },
            )

        raw_out, json_sections, extraction_mode = await loop.run_in_executor(None, run_extract)
        result = clean_text(raw_out)
        if json_sections is not None:
            result_sections = consolidate_sections(json_sections)
        else:
            result_sections = parse_extracted_sections(result)

        result_sections = augment_sections_for_missing_scrapes(
            result_sections,
            successful_sites,
            combined_text,
            sites["category"],
            sites.get("keyword", ""),
            sites.get("compare_targets") or [],
        )
        result_sections = consolidate_sections(result_sections)
        result_sections = polish_price_results(
            result_sections,
            sites.get("category", ""),
            sites.get("compare_targets") or [],
        )
        result_sections = polish_results_by_category(
            result_sections,
            sites.get("category", ""),
            sites.get("keyword", ""),
            sites.get("compare_targets") or [],
        )

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
