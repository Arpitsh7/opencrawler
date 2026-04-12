"""Structured extraction via Ollama (JSON when supported, with plain-text fallback)."""

from __future__ import annotations

import json
import re
import urllib.parse

import requests

from config import Settings, get_settings


def _normalize_host(url_or_host: str) -> str:
    s = (url_or_host or "").strip().lower()
    if "://" in s:
        try:
            s = urllib.parse.urlparse(s).netloc.lower()
        except Exception:
            return ""
    if s.startswith("www."):
        s = s[4:]
    return s


def _allowed_hosts_from_urls(urls: list[str]) -> list[str]:
    hosts: set[str] = set()
    for url in urls:
        h = _normalize_host(url)
        if h:
            hosts.add(h)
    return sorted(hosts)


def _parse_json_response(raw: str) -> dict | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _sections_from_json(data: dict) -> list[dict]:
    sections: list[dict] = []
    sources = data.get("sources")
    if not isinstance(sources, list):
        return sections

    for entry in sources:
        if not isinstance(entry, dict):
            continue
        if entry.get("no_data") is True:
            continue
        host = entry.get("host") or entry.get("hostname") or ""
        host = _normalize_host(str(host))
        summary = str(entry.get("summary") or "").strip()
        bullets = entry.get("bullets")
        if bullets is None:
            bullets = entry.get("items")
        if not isinstance(bullets, list):
            bullets = []
        items = [str(b).strip() for b in bullets if str(b).strip()]
        if not host and not summary and not items:
            continue
        label = host or "unknown"
        sections.append({"site": label, "summary": summary, "items": items})

    return sections


def _legacy_prompt(page_text: str, user_prompt: str) -> tuple[str, str]:
    system_prompt = """You are a web data extraction assistant.
Extract exactly what the user asks for from scraped webpage text.

STRICT FORMAT RULES:
- Always label each piece of data with its source site using the hostname from the scrape headers (e.g. amazon.in, flipkart.com)
- Output only source-labelled results. No introduction. No conclusion. No notes.
- Use this format only:
  hostname.example: data found
- Keep each source concise: at most 3 bullet points or 1 short summary
- If extracting prices, always show: hostname: Product - Price
- If the user asked to compare multiple products, keep the products separate
- If no relevant data is present for a site, write exactly: hostname: No data found
- Do not mention blocking, security, scraping problems, or reasons unless the user explicitly asked about that
- Never invent missing specifications, prices, or explanations
- Prefer exact facts present in the text over guesses
- Avoid long paragraphs. Prefer short bullets."""

    full_prompt = f"""SCRAPED CONTENT FROM MULTIPLE SITES:
{page_text}

USER REQUEST: {user_prompt}

Extract the requested information. For every SOURCE block in the content above,
show what was found or not found using the hostname from --- SOURCE: hostname --- lines.

If it is prices, format as:
hostname:
- Product name - Price

Never output more than 3 bullets for a single source."""

    return system_prompt, full_prompt


def extract_structured(
    page_text: str,
    user_prompt: str,
    source_urls: list[str],
    settings: Settings | None = None,
) -> tuple[str, list[dict] | None, str]:
    """
    Returns (raw_text_for_display, sections_or_none, mode).
    If sections_or_none is None, caller should parse raw_text with parse_extracted_sections.
    """
    settings = settings or get_settings()
    allowed = _allowed_hosts_from_urls(source_urls)
    host_lines = ", ".join(allowed) if allowed else "use hostnames from SOURCE headers"

    system_json = """You are a web data extraction assistant. Output ONLY valid JSON, no markdown.
Never invent prices or specs: only use facts visible in the scraped text.
You MUST include exactly one JSON object per hostname in the allowed list (same count as allowed hostnames)."""

    user_json = f"""Allowed hostnames — you MUST output one "sources" entry for EACH of these (use the string exactly as listed): {host_lines}

SCRAPED CONTENT:
{page_text}

USER REQUEST:
{user_prompt}

Return JSON with this exact shape:
{{
  "sources": [
    {{
      "host": "hostname-without-www",
      "summary": "one short sentence or empty string",
      "bullets": ["fact 1", "fact 2"],
      "no_data": false
    }}
  ]
}}

Rules:
- The "sources" array length MUST equal the number of allowed hostnames. One entry per host, no duplicates.
- At most 3 bullets per source. If a host has no useful facts for the request, set "no_data": true, "bullets": [], "summary": "".
- host must match one of the allowed hostnames (no www. prefix).
- Prefer bullets over long summaries for prices (Product — Price)."""

    try:
        response = requests.post(
            settings.ollama_generate_url,
            json={
                "model": settings.ollama_model,
                "prompt": user_json,
                "system": system_json,
                "stream": False,
                "format": "json",
            },
            timeout=settings.ollama_timeout_s,
        )
        if response.status_code == 200:
            raw = response.json().get("response", "").strip()
            data = _parse_json_response(raw)
            if data:
                sections = _sections_from_json(data)
                if sections:
                    return json.dumps(data, indent=2, ensure_ascii=False), sections, "json"
    except Exception as exc:
        print(f"JSON extraction path failed, falling back: {exc}")

    system_prompt, full_prompt = _legacy_prompt(page_text, user_prompt)
    response = requests.post(
        settings.ollama_generate_url,
        json={
            "model": settings.ollama_model,
            "prompt": full_prompt,
            "system": system_prompt,
            "stream": False,
        },
        timeout=settings.ollama_timeout_s,
    )

    if response.status_code != 200:
        raise RuntimeError(f"Ollama error: {response.status_code}")

    legacy = response.json().get("response", "").strip()
    return legacy, None, "legacy"


def extract_with_ai(page_text: str, user_prompt: str) -> str:
    """Plain-text extraction only (no JSON); kept for simple call sites."""
    settings = get_settings()
    system_prompt, full_prompt = _legacy_prompt(page_text, user_prompt)
    response = requests.post(
        settings.ollama_generate_url,
        json={
            "model": settings.ollama_model,
            "prompt": full_prompt,
            "system": system_prompt,
            "stream": False,
        },
        timeout=settings.ollama_timeout_s,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Ollama error: {response.status_code}")
    return response.json().get("response", "").strip()
