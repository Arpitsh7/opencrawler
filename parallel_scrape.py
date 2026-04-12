"""Concurrent async scraping against a shared Playwright browser."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from config import Settings, get_settings
from multi_scraper import TARGET_SUCCESSFUL_PAGES, _validate_scraped_text
from scraper_async import scrape_url_to_text
from trace_format import format_scrape_error

if TYPE_CHECKING:
    from playwright.async_api import Browser


async def _scrape_one(browser: "Browser", url: str, category: str, keyword: str, settings: Settings) -> dict:
    try:
        text = await scrape_url_to_text(browser, url, settings.scrape_timeout_ms, settings.scrape_wait_ms)
        status, error = _validate_scraped_text(url, text, category, keyword)
        if status != "ok":
            print(f"Failed ({error}, {len(text)} chars): {url}")
            return {"url": url, "status": status, "text": "", "error": error}

        print(f"OK ({len(text)} chars): {url}")
        return {"url": url, "status": "ok", "text": text, "error": ""}
    except Exception as exc:
        print(f"Exception scraping {url}: {exc}")
        return {"url": url, "status": "error", "text": "", "error": format_scrape_error(str(exc))}


async def scrape_all_async(browser: "Browser", sites: dict, settings: Settings | None = None) -> list[dict]:
    settings = settings or get_settings()
    category = sites.get("category", "general")
    keyword = sites.get("keyword", "")
    primary_urls = sites.get("primary", [])
    fallback_urls = sites.get("fallback", [])
    desired_successes = sites.get("target_successes", TARGET_SUCCESSFUL_PAGES)
    target_successes = min(
        desired_successes,
        max(1, len(primary_urls) + len(fallback_urls)),
    )

    queue: list[str] = []
    seen: set[str] = set()
    for url in primary_urls + fallback_urls:
        if url and url not in seen:
            seen.add(url)
            queue.append(url)

    max_workers = max(1, settings.scrape_concurrency)
    print(
        f"Trying {len(primary_urls)} primary and {len(fallback_urls)} fallback sites "
        f"(concurrency={max_workers}) to collect up to {target_successes} successful pages..."
    )

    results: list[dict] = []
    successful_count = 0
    semaphore = asyncio.Semaphore(max_workers)

    async def guarded(url: str) -> dict:
        async with semaphore:
            return await _scrape_one(browser, url, category, keyword, settings)

    in_flight: dict[asyncio.Task, str] = {}

    while (queue or in_flight) and successful_count < target_successes:
        while queue and len(in_flight) < max_workers and successful_count < target_successes:
            next_url = queue.pop(0)
            task = asyncio.create_task(guarded(next_url))
            in_flight[task] = next_url

        if not in_flight:
            break

        done, _ = await asyncio.wait(in_flight.keys(), return_when=asyncio.FIRST_COMPLETED)

        for task in done:
            url = in_flight.pop(task)
            result = await task
            results.append(result)

            if result["status"] == "ok":
                successful_count += 1
                print(f"Accepted: {url}")
            else:
                print(f"Rejected: {url} ({result['status']})")

        if successful_count >= target_successes:
            pending = list(in_flight.keys())
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            in_flight.clear()
            break

    return results
