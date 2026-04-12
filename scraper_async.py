"""Async Playwright scraping (shared browser, one context per page)."""

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING

from scraper import USER_AGENT

if TYPE_CHECKING:
    from playwright.async_api import Browser


def _extract_query_tokens(url: str, *param_names: str) -> list[str]:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    values = []
    for name in param_names:
        values.extend(query.get(name, []))

    tokens = []
    for value in values:
        tokens.extend(token.lower() for token in value.replace("+", " ").split() if token)
    return tokens


async def _find_best_matching_link(page, url: str, allowed_domains: list[str], exclude_fragments: list[str], query_params: list[str]) -> str | None:
    search_tokens = _extract_query_tokens(url, *query_params)
    candidates = await page.eval_on_selector_all(
        "a[href]",
        """els => els.map(e => ({
            href: e.href,
            text: (e.textContent || '').trim()
        })).filter(x => x.href)""",
    )

    scored = []
    seen = set()

    for candidate in candidates:
        href = candidate["href"]
        if href in seen:
            continue
        seen.add(href)

        href_lower = href.lower()
        text_lower = (candidate.get("text") or "").lower()

        if not any(domain in href_lower for domain in allowed_domains):
            continue
        if any(fragment in href_lower for fragment in exclude_fragments):
            continue

        score = 0
        for token in search_tokens:
            if token in href_lower:
                score += 10
            if token in text_lower:
                score += 14

        if "quote" in href_lower or "quote" in text_lower:
            score += 8

        if score > 0:
            scored.append((score, href))

    if not scored:
        return None

    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


async def _extract_best_gsmarena_match(page, url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    search_text = " ".join(query.get("sName", []))
    search_tokens = [token.lower() for token in search_text.replace("+", " ").split() if token]
    hrefs = await page.eval_on_selector_all(
        "a[href]",
        "els => els.map(e => e.href).filter(Boolean)",
    )

    candidates = []
    for href in hrefs:
        if "gsmarena.com/" not in href:
            continue
        if "-phones-" in href or "results.php3" in href or "search.php3" in href:
            continue
        score = 0
        href_lower = href.lower()
        for token in search_tokens:
            if token in href_lower:
                score += 10
        if score > 0 and href not in [c[1] for c in candidates]:
            candidates.append((score, href))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


async def _first_href_js(page, script: str) -> str | None:
    try:
        href = await page.evaluate(script)
        if href and isinstance(href, str) and href.startswith("http"):
            return href
    except Exception:
        return None
    return None


async def _follow_retail_listing(page, url: str) -> str | None:
    lower = url.lower()

    if "amazon.in" in lower and ("/s?" in lower or "/s/" in lower or "/gp/browse" in lower):
        return await _first_href_js(
            page,
            """() => {
              const links = Array.from(document.querySelectorAll('a[href*="/dp/"], a[href*="/gp/product/"]'));
              for (const a of links) {
                if (a.href && !a.href.includes('slredirect') && !a.href.includes('/help/')) return a.href;
              }
              return null;
            }""",
        )

    if "flipkart.com" in lower and "search" in lower:
        return await _first_href_js(
            page,
            """() => {
              const links = Array.from(document.querySelectorAll('a[href*="/p/"]'));
              for (const a of links) {
                if (a.href && a.href.includes('flipkart.com')) return a.href;
              }
              return null;
            }""",
        )

    if "samsung.com" in lower and "search" in lower:
        return await _first_href_js(
            page,
            """() => {
              const links = Array.from(document.querySelectorAll('a[href*="samsung.com"]'));
              for (const a of links) {
                const h = a.href || '';
                if (h.includes('/in/') && (h.includes('/smartphones/') || h.includes('/tablets/') || h.includes('/watches/')
                    || h.includes('/buds/') || h.includes('/tv/') || h.includes('/refrigerators/'))) return h;
              }
              return null;
            }""",
        )

    if "reliancedigital.in" in lower and "search" in lower:
        return await _first_href_js(
            page,
            """() => {
              const links = Array.from(document.querySelectorAll('a[href*="reliancedigital.in"]'));
              for (const a of links) {
                const h = (a.href || '').toLowerCase();
                if (h.includes('/product') || h.includes('/p/')) return a.href;
              }
              return null;
            }""",
        )

    if "croma.com" in lower and "search" in lower:
        return await _first_href_js(
            page,
            """() => {
              const links = Array.from(document.querySelectorAll('a[href*="croma.com"]'));
              for (const a of links) {
                const h = (a.href || '').toLowerCase();
                if (h.includes('/p/') || h.includes('/product')) return a.href;
              }
              return null;
            }""",
        )

    if "vijaysales.com" in lower and "search" in lower:
        return await _first_href_js(
            page,
            """() => {
              const links = Array.from(document.querySelectorAll('a[href*="vijaysales.com"]'));
              for (const a of links) {
                const h = (a.href || '').toLowerCase();
                if (h.includes('product') || h.includes('/p/')) return a.href;
              }
              return null;
            }""",
        )

    if "smartprix.com" in lower:
        return await _first_href_js(
            page,
            """() => {
              const links = Array.from(document.querySelectorAll('a[href*="smartprix.com"]'));
              for (const a of links) {
                const h = (a.href || '').toLowerCase();
                if (h.includes('/phones/') || h.includes('/pp') || h.includes('/mobiles/')) return a.href;
              }
              return null;
            }""",
        )

    if "91mobiles.com" in lower and "search" in lower:
        return await _first_href_js(
            page,
            """() => {
              const links = Array.from(document.querySelectorAll('a[href*="91mobiles.com"]'));
              for (const a of links) {
                const h = (a.href || '').toLowerCase();
                if (h.includes('/phone') || h.includes('/tablet') || h.includes('/price')) return a.href;
              }
              return null;
            }""",
        )

    return None


async def _resolve_detail_page(page, url: str) -> str | None:
    if "gsmarena.com/results.php3" in url:
        return await _extract_best_gsmarena_match(page, url)

    if "keepinspiring.me/" in url and "?s=" in url:
        return await _find_best_matching_link(
            page,
            url,
            allowed_domains=["keepinspiring.me/"],
            exclude_fragments=["/category/", "/page/", "#", "?s="],
            query_params=["s"],
        )

    if "inspiringquotes.com/search" in url:
        return await _find_best_matching_link(
            page,
            url,
            allowed_domains=["inspiringquotes.com/"],
            exclude_fragments=["/category/", "/authors/", "/search", "/subscribe", "#"],
            query_params=["q"],
        )

    return None


async def _goto_resilient(page, url: str, timeout_ms: int) -> None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception:
        await page.goto(url, wait_until="commit", timeout=min(timeout_ms, 25000))


MAX_TEXT_LENGTH = 12000


async def scrape_url_to_text(browser: "Browser", url: str, timeout_ms: int, wait_ms: int) -> str:
    settle_ms = max(wait_ms, 2000)
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1365, "height": 900},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        extra_http_headers={
            "Accept-Language": "en-IN,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    page = await context.new_page()
    try:
        nav_timeout = max(timeout_ms, 35000)
        await _goto_resilient(page, url, nav_timeout)
        await page.wait_for_timeout(settle_ms)

        detail_url = await _resolve_detail_page(page, url)
        if not detail_url:
            detail_url = await _follow_retail_listing(page, url)
        if detail_url and detail_url != url:
            await _goto_resilient(page, detail_url, nav_timeout)
            await page.wait_for_timeout(settle_ms)

        text = await page.evaluate(
            """() => {
                document.querySelectorAll('script,style,noscript').forEach(e => e.remove());
                return document.body ? document.body.innerText : '';
            }"""
        )
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)[:MAX_TEXT_LENGTH]
    finally:
        await context.close()
