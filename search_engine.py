import requests
from bs4 import BeautifulSoup
import urllib.parse

BLACKLIST = [
    "googleadservices.com",
    "googlesyndication.com",
    "doubleclick.net",
    "amazon-adsystem.com",
    "duckduckgo.com",
    "bing.com",
    "yahoo.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
]

def is_blocked(url: str) -> bool:
    url_lower = url.lower()
    for blocked in BLACKLIST:
        if blocked in url_lower:
            return True
    if "ad_domain" in url_lower or "ad_provider" in url_lower:
        return True
    return False

def search_duckduckgo(query: str, max_results: int = 6) -> list[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }

    search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"

    try:
        response = requests.get(search_url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")

        urls = []
        seen_domains = set()

        for result in soup.find_all("a", class_="result__a"):
            href = result.get("href", "")

            # decode DDG redirect
            if "uddg=" in href:
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                real_url = parsed.get("uddg", [None])[0]
                if real_url:
                    href = urllib.parse.unquote(real_url)

            if not href.startswith("http"):
                continue

            if is_blocked(href):
                print(f"Skipping: {href}")
                continue

            try:
                domain = href.split("/")[2]
            except:
                continue

            if domain in seen_domains:
                continue

            seen_domains.add(domain)
            urls.append(href)
            print(f"Found: {href}")

            if len(urls) >= max_results:
                break

        return urls

    except Exception as e:
        print(f"Search error: {e}")
        return []
