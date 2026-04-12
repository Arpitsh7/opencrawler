import sys
import urllib.parse
from playwright.sync_api import sync_playwright

MAX_TEXT_LENGTH = 12000

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
]


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


def _find_best_matching_link(page, url: str, allowed_domains: list[str], exclude_fragments: list[str], query_params: list[str]) -> str | None:
    search_tokens = _extract_query_tokens(url, *query_params)
    candidates = page.eval_on_selector_all(
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


def _extract_best_gsmarena_match(page, url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    search_text = " ".join(query.get("sName", []))
    search_tokens = [token.lower() for token in search_text.replace("+", " ").split() if token]
    hrefs = page.eval_on_selector_all(
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
        if score > 0 and href not in [candidate[1] for candidate in candidates]:
            candidates.append((score, href))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _first_href_js(page, script: str) -> str | None:
    try:
        href = page.evaluate(script)
        if href and isinstance(href, str) and href.startswith("http"):
            return href
    except Exception:
        return None
    return None


def _follow_retail_listing(page, url: str) -> str | None:
    """Open first plausible product/detail link from retailer search results."""
    lower = url.lower()

    if "amazon.in" in lower and ("/s?" in lower or "/s/" in lower or "/gp/browse" in lower):
        return _first_href_js(
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
        return _first_href_js(
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
        return _first_href_js(
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
        return _first_href_js(
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
        return _first_href_js(
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
        return _first_href_js(
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
        return _first_href_js(
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
        return _first_href_js(
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


def _resolve_detail_page(page, url: str) -> str | None:
    if "gsmarena.com/results.php3" in url:
        return _extract_best_gsmarena_match(page, url)

    if "keepinspiring.me/" in url and "?s=" in url:
        return _find_best_matching_link(
            page,
            url,
            allowed_domains=["keepinspiring.me/"],
            exclude_fragments=["/category/", "/page/", "#", "?s="],
            query_params=["s"],
        )

    if "inspiringquotes.com/search" in url:
        return _find_best_matching_link(
            page,
            url,
            allowed_domains=["inspiringquotes.com/"],
            exclude_fragments=["/category/", "/authors/", "/search", "/subscribe", "#"],
            query_params=["q"],
        )

    return None


def _block_heavy_assets(page, url: str) -> None:
    """Speed up slow retail pages (fewer images/fonts) to reduce subprocess timeouts."""
    lower = url.lower()
    if not any(
        d in lower
        for d in (
            "amazon.in",
            "vijaysales.com",
            "flipkart.com",
            "reliancedigital.in",
            "91mobiles.com",
        )
    ):
        return

    def _route_handler(route):
        try:
            if route.request.resource_type in ("image", "media", "font"):
                route.abort()
            else:
                route.continue_()
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    try:
        page.route("**/*", _route_handler)
    except Exception:
        pass


def _goto_resilient(page, url: str, timeout_ms: int) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception:
        page.goto(url, wait_until="commit", timeout=min(timeout_ms, 25000))


def scrape(url: str) -> str:
    timeout_ms = 45000
    settle_ms = 2200

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1365, "height": 900},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            extra_http_headers={
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        page = context.new_page()
        try:
            _block_heavy_assets(page, url)
            _goto_resilient(page, url, timeout_ms)
            listing = any(
                frag in url.lower()
                for frag in ("/s?k=", "/search", "search?", "/search/", "search_result", "searchb?")
            )
            page.wait_for_timeout(1000 if listing else settle_ms)

            detail_url = _resolve_detail_page(page, url)
            if not detail_url:
                detail_url = _follow_retail_listing(page, url)
            if detail_url and detail_url != url:
                _goto_resilient(page, detail_url, timeout_ms)
                page.wait_for_timeout(settle_ms)

            text = page.evaluate(
                """() => {
                document.querySelectorAll('script,style,noscript').forEach(e => e.remove());
                return document.body ? document.body.innerText : '';
            }"""
            )
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return "\n".join(lines)[:MAX_TEXT_LENGTH]
        finally:
            context.close()
            browser.close()


def _scrape_sync(url: str) -> str:
    return scrape(url)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print("Usage: scraper.py <url>", file=sys.stderr)
        sys.exit(2)
    url = sys.argv[1]
    try:
        print(scrape(url))
    except Exception as exc:
        print(f"SCRAPE_ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
