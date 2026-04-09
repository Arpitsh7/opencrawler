import requests


def extract_with_ai(page_text: str, user_prompt: str) -> str:
    system_prompt = """You are a web data extraction assistant.
Extract exactly what the user asks for from scraped webpage text.

STRICT FORMAT RULES:
- Always label each piece of data with its source site
- Output only source-labelled results. No introduction. No conclusion. No notes.
- Use this format only:
  [Site Name]: data found
- Keep each source concise: at most 3 bullet points or 1 short summary
- If extracting prices, always show: [Site]: Product - Price
- If no relevant data is present for a site, write exactly: [Site Name]: No data found
- Do not mention blocking, security, scraping problems, or reasons unless the user explicitly asked about that
- Never invent missing specifications, prices, or explanations
- Prefer exact facts present in the text over guesses
- Avoid long paragraphs. Prefer short bullets."""

    full_prompt = f"""SCRAPED CONTENT FROM MULTIPLE SITES:
{page_text}

USER REQUEST: {user_prompt}

Extract the requested information. For every source site in the content above,
show what was found or not found.

Allowed output format:
[Site Name]: extracted data here

If it is prices, format as:
[Site Name]:
- Product name - Price
- Product name - Price

If it is specifications, list only concrete fields that are present in the scraped text.
Never output more than 3 bullets for a single source."""

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "llama3",
            "prompt": full_prompt,
            "system": system_prompt,
            "stream": False,
        },
        timeout=120,
    )

    if response.status_code == 200:
        return response.json()["response"]

    raise Exception(f"Ollama error: {response.status_code}")
