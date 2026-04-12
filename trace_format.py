"""Short, UI-safe messages for scrape / subprocess errors (no full Windows paths or argv dumps)."""

from __future__ import annotations

import re


def format_scrape_error(raw: str | None, max_len: int = 160) -> str:
    if not raw:
        return ""
    text = " ".join(str(raw).strip().split())
    lowered = text.lower()

    if "timed out after" in lowered or "timeoutexpired" in lowered or "timeout expired" in lowered:
        return "subprocess_timeout"
    if "temporary_error" in lowered:
        return "temporary_error"
    if "blocked_page" in lowered or "access denied" in lowered:
        return "blocked"
    if "too_short" in lowered:
        return "too_short"
    if "no_results" in lowered or "page not found" in lowered:
        return "no_results"

    # Playwright / scraper stderr: "SCRAPE_ERROR: ..."
    m = re.search(r"SCRAPE_ERROR:\s*(.+)$", text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        text = m.group(1).strip()
        lowered = text.lower()

    # subprocess.run failure: Command '['C:\\...python.exe', 'scraper.py', 'url']' ...
    if text.startswith("Command ") or ("scraper.py" in lowered and "python" in lowered):
        if "timed out" in lowered:
            return "subprocess_timeout"
        if "notimplementederror" in lowered:
            return "playwright_not_supported"
        return "scraper_subprocess_failed"

    # Strip long Windows / Unix paths from any remaining message
    text = re.sub(r"[A-Za-z]:\\(?:[^\\]|\\)+?\.(?:exe|PY|py)", "[bin]", text)
    text = re.sub(r"/(?:usr|opt|home)/[^\s]+/python[\d.]*", "[python]", text)

    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text
