"""Configuration shared by the CLI, engine and source adapters."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    headless: bool = True
    browser_timeout: int = 30_000
    scroll_count: int = 6
    scroll_delay: float = 2.0
    result_click_delay: float = 1.5
    min_delay: float = 1.0
    max_delay: float = 3.0

    website_timeout: float = 6
    website_budget: float = 20
    website_max_requests: int = 8
    website_max_bytes: int = 750_000
    contact_paths: tuple[str, ...] = ("/contact", "/mentions-legales")
    max_description_length: int = 300
    max_concurrent_website_scrapers: int = 5
    max_concurrent_sources: int = 3
    source_timeout: int = 240
    legacy_proxy: str | None = None

    output_dir: str = "results"
    output_format: str = "both"
    filter_junk: bool = True
    filter_empty: bool = True
    min_score: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.max_concurrent_website_scrapers <= 20:
            raise ValueError("Website concurrency must be between 1 and 20")
        if self.max_concurrent_sources < 1 or self.scroll_count < 0:
            raise ValueError("Invalid source concurrency or scroll count")
        if not str(self.output_dir).strip() or self.output_format not in {"json", "csv", "both"}:
            raise ValueError("Invalid export directory or format")


def database_url() -> str | None:
    import os

    if filename := os.getenv("DATABASE_URL_FILE"):
        return Path(filename).read_text(encoding="utf-8").strip()
    return os.getenv("DATABASE_URL") or None
