"""Pick the most relevant slice of long page text for the LLM context window."""

from __future__ import annotations

import re

# Signals that often surround the answer the user cares about
_PRICE_HINTS = ("₹", "rs.", "inr", "price", "mrp", "deal", "off", "buy", "cart", "emi")
_SPEC_HINTS = (
    "display",
    "battery",
    "camera",
    "ram",
    "storage",
    "processor",
    "chipset",
    "android",
    "dimensions",
    "weight",
    "mah",
    "mp",
    "ghz",
)
_NEWS_HINTS = ("published", "updated", "report", "said", "according", "breaking", "hours ago")


def _keyword_tokens(keyword: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", keyword.lower()) if len(t) > 2]


def _score_chunk(lower_chunk: str, tokens: list[str], category: str) -> int:
    score = sum(lower_chunk.count(t) for t in tokens)
    hints = ()
    if category == "prices":
        hints = _PRICE_HINTS
    elif category == "tech_specs":
        hints = _SPEC_HINTS
    elif category == "news":
        hints = _NEWS_HINTS
    score += sum(3 for h in hints if h in lower_chunk)
    return score


def select_relevant_excerpt(text: str, keyword: str, category: str, max_chars: int) -> str:
    if not text or max_chars <= 0:
        return ""
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned

    tokens = _keyword_tokens(keyword)
    lower_full = cleaned.lower()
    best_start = 0
    best_score = -1
    window = max_chars
    # Sample start positions; full scan is O(n*window) which is fine for ~8k text
    step = max(200, window // 8)
    for start in range(0, len(cleaned) - window + 1, step):
        chunk = cleaned[start : start + window]
        sc = _score_chunk(chunk.lower(), tokens, category)
        if sc > best_score:
            best_score = sc
            best_start = start

    # If keyword tokens never matched, bias toward price/spec hints from the start
    if best_score <= 0 and tokens:
        for t in tokens:
            pos = lower_full.find(t)
            if pos != -1:
                best_start = max(0, pos - min(400, max_chars // 4))
                break

    excerpt = cleaned[best_start : best_start + window].strip()
    if len(excerpt) < max_chars * 0.5:
        excerpt = cleaned[:max_chars].strip()
    return excerpt
