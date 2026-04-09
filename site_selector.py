import re
import urllib.parse

import requests

from search_engine import search_duckduckgo

CATEGORY_CONFIG = {
    "prices": {
        "search_suffix": "price buy compare review",
        "primary_limit": 4,
        "fallback_limit": 8,
        "target_successes": 3,
        "preferred_domains": [
            "amazon.in",
            "flipkart.com",
            "samsung.com",
            "reliancedigital.in",
            "vijaysales.com",
            "croma.com",
            "smartprix.com",
            "91mobiles.com",
        ],
        "seed_urls": [
            "https://www.amazon.in/s?k=",
            "https://www.flipkart.com/search?q=",
            "https://www.samsung.com/in/search/?searchvalue=",
            "https://www.reliancedigital.in/search?q=",
            "https://www.vijaysales.com/search/",
            "https://www.croma.com/searchB?q=",
            "https://www.smartprix.com/products/?q=",
            "https://www.91mobiles.com/search_result.php?q=",
        ],
    },
    "quotes": {
        "search_suffix": "quotes sayings inspiration",
        "primary_limit": 4,
        "fallback_limit": 5,
        "target_successes": 3,
        "preferred_domains": [
            "wikiquote.org",
            "keepinspiring.me",
            "quotes.toscrape.com",
            "inspiringquotes.com",
            "brainyquote.com",
        ],
        "seed_urls": [
            "https://en.wikiquote.org/w/index.php?search=",
            "https://www.keepinspiring.me/?s=",
            "https://quotes.toscrape.com/search.aspx?q=",
            "https://inspiringquotes.com/search/?q=",
        ],
    },
    "news": {
        "search_suffix": "latest news",
        "primary_limit": 4,
        "fallback_limit": 6,
        "target_successes": 3,
        "preferred_domains": [
            "reuters.com",
            "apnews.com",
            "bbc.com",
            "techcrunch.com",
            "theverge.com",
            "indianexpress.com",
            "ndtv.com",
            "timesofindia.indiatimes.com",
        ],
        "seed_urls": [
            "https://news.google.com/search?q=",
            "https://www.reuters.com/search/news?blob=",
            "https://www.bbc.com/search?q=",
            "https://techcrunch.com/search/",
        ],
    },
    "tech_specs": {
        "search_suffix": "specifications features review",
        "primary_limit": 4,
        "fallback_limit": 6,
        "target_successes": 2,
        "preferred_domains": [
            "gsmarena.com",
            "91mobiles.com",
            "notebookcheck.net",
            "smartprix.com",
            "digit.in",
        ],
        "seed_urls": [
            "https://www.gsmarena.com/results.php3?sQuickSearch=yes&sName=",
            "https://www.91mobiles.com/search_result.php?q=",
            "https://www.notebookcheck.net/Search.8222.0.html?ns_query=",
            "https://www.smartprix.com/products/?q=",
        ],
    },
    "jobs": {
        "search_suffix": "jobs openings careers",
        "primary_limit": 4,
        "fallback_limit": 6,
        "target_successes": 3,
        "preferred_domains": [
            "linkedin.com",
            "indeed.com",
            "naukri.com",
            "wellfound.com",
            "foundit.in",
            "glassdoor.com",
        ],
        "seed_urls": [
            "https://www.linkedin.com/jobs/search/?keywords=",
            "https://in.indeed.com/jobs?q=",
            "https://www.naukri.com/",
            "https://www.foundit.in/srp/results?query=",
        ],
    },
    "general": {
        "search_suffix": "",
        "primary_limit": 3,
        "fallback_limit": 5,
        "target_successes": 2,
        "preferred_domains": [
            "wikipedia.org",
            "britannica.com",
            "mozilla.org",
            "python.org",
            "github.com",
            "stackoverflow.com",
        ],
        "seed_urls": [],
    },
}

DEFAULT_CATEGORY = "general"
PRIMARY_LIMIT = 3
FALLBACK_LIMIT = 5
CATEGORY_KEYWORDS = {
    "prices": [
        "price", "prices", "cost", "buy", "deal", "discount", "cheapest", "compare price",
        "offer", "offers", "sale", "mrp",
    ],
    "quotes": [
        "quote", "quotes", "saying", "sayings", "inspiration", "motivational quote",
        "caption", "captions",
    ],
    "news": [
        "news", "latest", "headline", "headlines", "update", "updates", "breaking",
    ],
    "tech_specs": [
        "spec", "specs", "specification", "specifications", "features", "ram", "battery",
        "camera", "display", "processor", "chipset",
    ],
    "jobs": [
        "job", "jobs", "hiring", "opening", "openings", "career", "careers", "vacancy",
        "vacancies", "role", "roles", "recruitment",
    ],
}


def _ollama_generate(prompt: str, default: str) -> str:
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3",
                "prompt": prompt,
                "stream": False,
            },
            timeout=30,
        )
        response.raise_for_status()
        value = response.json().get("response", "").strip()
        return value or default
    except Exception as exc:
        print(f"Ollama unavailable, using fallback value '{default}': {exc}")
        return default


def get_search_keyword(user_request: str) -> str:
    prompt = f"""Extract the main search keyword from this request.
Return ONLY the keyword(s), nothing else.
Examples:
- get me iPhone 15 prices -> iPhone 15
- find quotes about success -> success
- latest AI news -> AI news
- software engineer jobs in Delhi -> software engineer Delhi

Request: {user_request}"""
    return _ollama_generate(prompt, user_request.strip())


def get_search_keyword_fallback(user_request: str, category: str) -> str:
    text = user_request.strip()
    lowered = text.lower()

    if category == "quotes":
        cleaned = re.sub(r"\b(get me|find|show|give me|quotes?|about|on|for)\b", " ", lowered)
        cleaned = " ".join(cleaned.split()).strip()
        return cleaned.title() if cleaned else text

    if category == "prices":
        cleaned = re.sub(
            r"\b(compare|price|prices|cost|buy|deal|deals|offers?|sale|in india|cheap|cheapest)\b",
            " ",
            lowered,
        )
        cleaned = " ".join(cleaned.split()).strip()
        return cleaned.title() if cleaned else text

    if category == "tech_specs":
        cleaned = re.sub(
            r"\b(spec|specs|specification|specifications|features|ram|battery|camera|display|processor|chipset)\b",
            " ",
            lowered,
        )
        cleaned = " ".join(cleaned.split()).strip()
        return cleaned.title() if cleaned else text

    if category == "news":
        cleaned = re.sub(r"\b(latest|news|headlines|headline|updates?|breaking|today)\b", " ", lowered)
        cleaned = " ".join(cleaned.split()).strip()
        return cleaned.title() if cleaned else text

    if category == "jobs":
        cleaned = re.sub(r"\b(job|jobs|hiring|opening|openings|career|careers|vacancy|vacancies|role|roles)\b", " ", lowered)
        cleaned = " ".join(cleaned.split()).strip()
        return cleaned.title() if cleaned else text

    return text


def heuristic_category(user_request: str) -> str:
    lowered = user_request.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return DEFAULT_CATEGORY


def get_category(user_request: str) -> str:
    heuristic = heuristic_category(user_request)
    if heuristic != DEFAULT_CATEGORY:
        return heuristic

    prompt = f"""Classify this user request into ONE category.
Choose from: prices, quotes, news, tech_specs, jobs, general
Return ONLY the category word, nothing else.

Request: {user_request}"""
    category = _ollama_generate(prompt, DEFAULT_CATEGORY).strip().lower()
    return category if category in CATEGORY_CONFIG else DEFAULT_CATEGORY


def _normalize_domain(url: str) -> str:
    domain = urllib.parse.urlparse(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2]


def _build_seed_urls(category: str, keyword: str) -> list[str]:
    encoded_keyword = urllib.parse.quote_plus(keyword)
    urls = []
    for base_url in CATEGORY_CONFIG[category]["seed_urls"]:
        if "=" in base_url:
            urls.append(base_url + encoded_keyword)
        elif category == "prices" and "vijaysales.com/search/" in base_url:
            urls.append(base_url + encoded_keyword)
        else:
            urls.append(base_url)
    return urls


def _build_search_queries(category: str, keyword: str) -> list[str]:
    suffix = CATEGORY_CONFIG[category]["search_suffix"].strip()
    queries = [keyword]

    if suffix:
        queries.append(f"{keyword} {suffix}")

    if category == "news":
        queries.append(f"{keyword} latest headlines")
    elif category == "jobs":
        queries.append(f"{keyword} jobs site:linkedin.com OR site:indeed.com OR site:naukri.com")
    elif category == "tech_specs":
        queries.append(f"{keyword} full specifications")
    elif category == "prices":
        queries.append(f"{keyword} price in india")

    seen = set()
    ordered = []
    for query in queries:
        clean = " ".join(query.split())
        if clean and clean not in seen:
            seen.add(clean)
            ordered.append(clean)
    return ordered


def _score_url(url: str, category: str, keyword: str) -> int:
    domain = _normalize_domain(url)
    parsed = urllib.parse.urlparse(url)
    url_text = f"{parsed.path} {parsed.query}".lower()
    keyword_tokens = _tokenize(keyword)
    preferred_domains = CATEGORY_CONFIG[category]["preferred_domains"]

    score = 0

    for index, preferred in enumerate(preferred_domains):
        if preferred in domain:
            score += 120 - (index * 10)
            break

    for token in keyword_tokens:
        if token in domain:
            score += 30
        if token in url_text:
            score += 12

    if category == "news":
        if any(fragment in url_text for fragment in ["news", "article", "story", "live"]):
            score += 15
    elif category == "jobs":
        if any(fragment in url_text for fragment in ["job", "jobs", "career", "hiring"]):
            score += 15
    elif category == "tech_specs":
        if any(fragment in url_text for fragment in ["spec", "specs", "review", "compare"]):
            score += 15
    elif category == "prices":
        if any(fragment in url_text for fragment in ["price", "buy", "product", "p=", "search"]):
            score += 15

    if any(fragment in url_text for fragment in ["search", "results"]):
        score += 5

    return score


def _rank_candidates(category: str, keyword: str, candidates: list[str]) -> list[str]:
    scored = []
    seen_urls = set()

    for url in candidates:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        scored.append((_score_url(url, category, keyword), url))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [url for score, url in scored if score > 0]


def _split_primary_and_fallback(
    category: str,
    urls: list[str]
) -> tuple[list[str], list[str]]:
    primary = []
    fallback = []
    primary_domains = set()
    primary_limit = CATEGORY_CONFIG[category].get("primary_limit", PRIMARY_LIMIT)
    fallback_limit = CATEGORY_CONFIG[category].get("fallback_limit", FALLBACK_LIMIT)

    for url in urls:
        domain = _normalize_domain(url)
        if len(primary) < primary_limit and domain not in primary_domains:
            primary.append(url)
            primary_domains.add(domain)
            continue
        if len(fallback) < fallback_limit and url not in primary:
            fallback.append(url)
        if len(primary) >= primary_limit and len(fallback) >= fallback_limit:
            break

    return primary, fallback


def select_sites(user_request: str) -> dict:
    category = get_category(user_request)
    keyword = get_search_keyword(user_request)
    if not keyword or keyword.strip().lower() == user_request.strip().lower():
        keyword = get_search_keyword_fallback(user_request, category)

    queries = _build_search_queries(category, keyword)
    discovered_urls = []
    for query in queries:
        discovered_urls.extend(search_duckduckgo(query, max_results=8))

    ranked_urls = _rank_candidates(category, keyword, discovered_urls)
    primary_limit = CATEGORY_CONFIG[category].get("primary_limit", PRIMARY_LIMIT)

    if len(ranked_urls) < primary_limit:
        ranked_urls.extend(
            url for url in _build_seed_urls(category, keyword) if url not in ranked_urls
        )

    primary, fallback = _split_primary_and_fallback(category, ranked_urls)

    if not primary:
        seed_urls = _build_seed_urls(category, keyword)
        primary_limit = CATEGORY_CONFIG[category].get("primary_limit", PRIMARY_LIMIT)
        fallback_limit = CATEGORY_CONFIG[category].get("fallback_limit", FALLBACK_LIMIT)
        primary = seed_urls[:primary_limit]
        fallback = seed_urls[primary_limit:primary_limit + fallback_limit]

    return {
        "category": category,
        "keyword": keyword,
        "queries": queries,
        "primary": primary,
        "fallback": fallback,
        "target_successes": CATEGORY_CONFIG[category].get("target_successes", 2),
    }
