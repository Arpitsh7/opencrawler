import sys
import urllib.parse
from playwright.sync_api import sync_playwright

MAX_TEXT_LENGTH = 8000


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
        })).filter(x => x.href)"""
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
        "els => els.map(e => e.href).filter(Boolean)"
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


def scrape(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1200)

            detail_url = _resolve_detail_page(page, url)
            if detail_url:
                page.goto(detail_url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(1200)

            text = page.evaluate("""() => {
                document.querySelectorAll('script,style,nav,footer,noscript').forEach(e => e.remove());
                return document.body ? document.body.innerText : '';
            }""")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return "\n".join(lines)[:MAX_TEXT_LENGTH]
        finally:
            browser.close()


def _scrape_sync(url: str) -> str:
    return scrape(url)

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    url = sys.argv[1]
    print(scrape(url))
