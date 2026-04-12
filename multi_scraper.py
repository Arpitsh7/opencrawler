import subprocess
import sys
import os
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

MIN_TEXT_LENGTH = 280
SCRAPER_SUBPROCESS_TIMEOUT_S = 60
MAX_WORKERS = 3
TARGET_SUCCESSFUL_PAGES = 2
BLOCK_INDICATORS = [
    "sorry, you have been blocked",
    "access denied",
    "security service",
    "cloudflare ray id",
    "captcha",
    "verify you are human",
]
TECH_SPECS_SIGNALS = [
    "display",
    "battery",
    "camera",
    "chipset",
    "ram",
    "storage",
    "android",
    "dimensions",
]
PRICE_SIGNALS = [
    "₹",
    "rs.",
    "price",
    "m.r.p",
    "deal",
    "add to cart",
    "buy now",
    "off",
]
NO_RESULTS_SIGNALS = [
    "no results for",
    "0 results",
    "did not match any products",
    "page was not found",
    "page not found",
    "try a new search",
]
# Keep specific — generic phrases like "service unavailable" appear in site footers.
TRANSIENT_ERROR_SIGNALS = [
    "it's rush hour and traffic is piling up on that page",
    "please try again in a short while",
    "temporarily unavailable",
]


def _is_blocked_page(text: str) -> bool:
    lower_text = text.lower()
    return any(signal in lower_text for signal in BLOCK_INDICATORS)


def _is_no_results_page(text: str) -> bool:
    lower_text = text.lower()
    return any(signal in lower_text for signal in NO_RESULTS_SIGNALS)


def _is_transient_error_page(text: str) -> bool:
    if len(text) > 3200:
        return False
    lower_text = text.lower()
    return any(signal in lower_text for signal in TRANSIENT_ERROR_SIGNALS)


def _keyword_token_matches(text: str, keyword: str) -> int:
    tokens = [token for token in re.findall(r"[a-z0-9]+", keyword.lower()) if len(token) > 2]
    lower_text = text.lower()
    return sum(1 for token in tokens if token in lower_text)


def _looks_like_price_page(text: str, keyword: str) -> bool:
    lower_text = text.lower()
    signal_hits = sum(1 for signal in PRICE_SIGNALS if signal in lower_text)
    token_hits = _keyword_token_matches(text, keyword)
    if signal_hits >= 2 and token_hits >= 1:
        return True
    if signal_hits >= 1 and token_hits >= 1 and len(text) >= 100:
        return True
    return False


def _looks_like_search_or_listing(url: str) -> bool:
    lower = url.lower()
    return any(
        fragment in lower
        for fragment in ("/s?k=", "/search", "search?q", "/s/", "/sr?", "/gp/browse", "search_result", "searchb?")
    )


def _looks_like_thin_search_page(url: str, text: str, category: str) -> bool:
    lower_url = url.lower()
    lower_text = text.lower()

    if category != "tech_specs":
        return False

    is_search_url = any(fragment in lower_url for fragment in ["search", "results", "finder"])
    has_spec_signal = sum(1 for signal in TECH_SPECS_SIGNALS if signal in lower_text) >= 2

    return is_search_url and not has_spec_signal


def _validate_scraped_text(url: str, text: str, category: str, keyword: str) -> tuple[str, str]:
    if _is_blocked_page(text):
        return "blocked", "blocked_page"

    if _is_no_results_page(text):
        return "empty", "no_results"

    if _is_transient_error_page(text):
        return "error", "temporary_error"

    if category == "prices" and _looks_like_price_page(text, keyword):
        return "ok", ""

    min_len = MIN_TEXT_LENGTH
    if category == "prices" and _looks_like_search_or_listing(url) and _looks_like_price_page(text, keyword):
        min_len = 120

    if len(text) < min_len:
        return "empty", "too_short"

    if _looks_like_thin_search_page(url, text, category):
        return "empty", "thin_search_page"

    return "ok", ""


def scrape_one(url: str, category: str = "general", keyword: str = "") -> dict:
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        result = subprocess.run(
            [sys.executable, "scraper.py", url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SCRAPER_SUBPROCESS_TIMEOUT_S,
            cwd=base_dir,
        )
        if result.returncode != 0:
            error_text = (result.stderr or result.stdout).strip()
            print(f"Failed (returncode {result.returncode}): {url}")
            return {"url": url, "status": "error", "text": "", "error": error_text}

        text = result.stdout.strip()
        status, error = _validate_scraped_text(url, text, category, keyword)
        if status != "ok":
            print(f"Failed ({error}, {len(text)} chars): {url}")
            return {"url": url, "status": status, "text": "", "error": error}

        print(f"OK ({len(text)} chars): {url}")
        return {"url": url, "status": "ok", "text": text, "error": ""}

    except Exception as e:
        print(f"Exception scraping {url}: {e}")
        return {"url": url, "status": "error", "text": "", "error": str(e)}

def scrape_all(sites: dict) -> list[dict]:
    category = sites.get("category", "general")
    keyword = sites.get("keyword", "")
    primary_urls = sites.get("primary", [])
    fallback_urls = sites.get("fallback", [])
    desired_successes = sites.get("target_successes", TARGET_SUCCESSFUL_PAGES)
    target_successes = min(
        desired_successes,
        max(1, len(primary_urls) + len(fallback_urls))
    )

    queue = []
    seen = set()
    for url in primary_urls + fallback_urls:
        if url and url not in seen:
            seen.add(url)
            queue.append(url)

    print(
        f"Trying {len(primary_urls)} primary and {len(fallback_urls)} fallback sites "
        f"to collect up to {target_successes} successful pages..."
    )

    results = []
    successful_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        in_flight = {}

        while queue and len(in_flight) < MAX_WORKERS:
            next_url = queue.pop(0)
            in_flight[executor.submit(scrape_one, next_url, category, keyword)] = next_url

        while in_flight:
            done, _ = wait(in_flight.keys(), return_when=FIRST_COMPLETED)

            for future in done:
                url = in_flight.pop(future)
                result = future.result()
                results.append(result)

                if result["status"] == "ok":
                    successful_count += 1
                    print(f"Accepted: {url}")
                else:
                    print(f"Rejected: {url} ({result['status']})")

                if successful_count >= target_successes:
                    for pending_future in in_flight:
                        pending_future.cancel()
                    return results

                if queue:
                    next_url = queue.pop(0)
                    in_flight[executor.submit(scrape_one, next_url, category, keyword)] = next_url

    return results
