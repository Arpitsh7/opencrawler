from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from pydantic import BaseModel
import re
from site_selector import select_sites
from multi_scraper import scrape_all
from ai_extractor import extract_with_ai

app = FastAPI()
templates = Jinja2Templates(directory="templates")
MOJIBAKE_REPLACEMENTS = {
    "â‚¹": "₹",
    "â€”": " - ",
    "â€“": " - ",
    "â€˜": "'",
    "â€™": "'",
    "â€œ": '"',
    "â€": '"',
}

class AgentRequest(BaseModel):
    request: str


def clean_text(value: str) -> str:
    cleaned = value
    for wrong, right in MOJIBAKE_REPLACEMENTS.items():
        cleaned = cleaned.replace(wrong, right)
    return cleaned


def normalize_site_label(value: str) -> str:
    cleaned = clean_text(value).strip()
    cleaned = re.sub(r"^\*+|\*+$", "", cleaned).strip()
    cleaned = re.sub(r"^\[|\]$", "", cleaned).strip()
    return cleaned


def summarize_error(value: str) -> str:
    text = clean_text(value or "").strip()
    if not text:
        return ""

    lowered = text.lower()
    if "timeout" in lowered:
        return "timeout"
    if "temporary_error" in lowered:
        return "temporary_error"
    if "blocked" in lowered or "access denied" in lowered:
        return "blocked"
    if "too_short" in lowered:
        return "too_short"
    if "page not found" in lowered or "not found" in lowered:
        return "not_found"

    first_line = text.splitlines()[0].strip()
    return first_line[:80]


def split_summary_into_items(summary: str) -> tuple[str, list[str]]:
    cleaned = clean_text(summary).strip()
    if not cleaned:
        return "", []

    parts = [part.strip() for part in re.split(r"\s+\*\s+", cleaned.lstrip("* ").strip()) if part.strip()]
    if len(parts) > 1:
        return "", parts

    return cleaned, []


def is_no_data_text(value: str) -> bool:
    normalized = clean_text(value or "").strip().lower()
    normalized = re.sub(r"^[\-\*\u2022\.\s]+", "", normalized).strip()
    return normalized in {
        "no data found",
        "no relevant data found",
        "no specific data found",
        "no prices mentioned",
        "no specific price mentioned",
    }


def parse_extracted_sections(extracted_text: str) -> list[dict]:
    sections = []
    current = None

    for raw_line in clean_text(extracted_text).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        header_match = re.match(r"^\[?([^\]]+?)\]?\s*:\s*(.*)$", line)
        if header_match and (
            "." in header_match.group(1) or header_match.group(1).lower().startswith("site")
        ):
            if current:
                sections.append(current)
            detail = header_match.group(2).strip()
            current = {
                "site": normalize_site_label(header_match.group(1)),
                "summary": detail if detail and not detail.startswith("-") else "",
                "items": [],
            }
            if detail.startswith("-"):
                current["items"].append(detail[1:].strip())
            continue

        if current is None:
            continue

        if line.startswith("-"):
            current["items"].append(line[1:].strip())
        elif current["summary"]:
            current["summary"] += " " + line
        else:
            current["summary"] = line

    if current:
        sections.append(current)

    filtered_sections = []
    for section in sections:
        summary = clean_text(section.get("summary", "")).strip()
        items = [clean_text(item).strip() for item in section.get("items", []) if clean_text(item).strip()]
        if not items and "*" in summary:
            summary, inferred_items = split_summary_into_items(summary)
            items.extend(inferred_items)
        items = [item for item in items if not is_no_data_text(item)]
        if is_no_data_text(summary):
            continue
        if not summary and not items:
            continue
        filtered_sections.append(
            {
                "site": normalize_site_label(section.get("site", "")),
                "summary": summary,
                "items": items,
            }
        )

    return filtered_sections

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/agent")
async def agent(data: AgentRequest):
    try:
        # Step 1: Choose search queries and candidate sites
        sites = select_sites(data.request)
        print(
            f"Category={sites['category']} Keyword={sites['keyword']} "
            f"Queries={sites.get('queries', [])}"
        )
        print(f"Primary sites: {sites['primary']}")
        print(f"Fallback sites: {sites['fallback']}")

        # Step 2: Scrape with fallback logic
        scraped = scrape_all(sites)

        # Step 3: Combine successful results
        combined_text = ""
        successful_sites = []
        scrape_summary = []

        for r in scraped:
            scrape_summary.append(
                {
                    "url": r["url"],
                    "status": r["status"],
                    "error": summarize_error(r.get("error", "")),
                    "text_length": len(r.get("text", "")),
                }
            )
            if r["status"] == "ok" and r["text"]:
                try:
                    hostname = r['url'].split('/')[2]
                except:
                    hostname = r['url']
                combined_text += f"\n\n--- SOURCE: {hostname} ---\n{r['text'][:3000]}"
                successful_sites.append(r["url"])

        if not combined_text:
            return {
                "status": "error",
                "message": "All sites blocked or returned no data. Try a different request.",
                "debug": {
                    "category": sites["category"],
                    "keyword": sites["keyword"],
                    "queries": sites.get("queries", []),
                    "primary": sites["primary"],
                    "fallback": sites["fallback"],
                    "scrape_summary": scrape_summary,
                },
            }

        # Step 4: AI extracts structured result
        print(f"Sending {len(successful_sites)} pages to Ollama...")
        result = clean_text(extract_with_ai(combined_text, data.request))
        result_sections = parse_extracted_sections(result)

        return {
            "status": "success",
            "sites_scraped": successful_sites,
            "visible_source_count": len(result_sections),
            "category": sites["category"],
            "keyword": sites["keyword"],
            "extracted": result,
            "result_sections": result_sections,
            "debug": {
                "queries": sites.get("queries", []),
                "primary": sites["primary"],
                "fallback": sites["fallback"],
                "scrape_summary": scrape_summary,
            },
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}
