"""Runtime configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_s: int
    ollama_keyword_timeout_s: int
    scrape_timeout_ms: int
    scrape_wait_ms: int
    scrape_concurrency: int
    max_chars_per_source: int
    search_urls_per_domain: int
    search_max_results_per_query: int

    @property
    def ollama_generate_url(self) -> str:
        return f"{self.ollama_base_url.rstrip('/')}/api/generate"


@lru_cache
def get_settings() -> Settings:
    return Settings(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3"),
        ollama_timeout_s=int(os.getenv("OLLAMA_TIMEOUT_S", "180")),
        ollama_keyword_timeout_s=int(os.getenv("OLLAMA_KEYWORD_TIMEOUT_S", "45")),
        scrape_timeout_ms=int(os.getenv("SCRAPE_TIMEOUT_MS", "28000")),
        scrape_wait_ms=int(os.getenv("SCRAPE_WAIT_MS", "1200")),
        scrape_concurrency=int(os.getenv("SCRAPE_CONCURRENCY", "4")),
        max_chars_per_source=int(os.getenv("MAX_CHARS_PER_SOURCE", "5200")),
        search_urls_per_domain=int(os.getenv("SEARCH_URLS_PER_DOMAIN", "2")),
        search_max_results_per_query=int(os.getenv("SEARCH_MAX_RESULTS_PER_QUERY", "12")),
    )
