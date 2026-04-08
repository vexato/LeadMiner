"""Central configuration for the LeadMiner scraper."""

from dataclasses import dataclass, field


@dataclass
class Settings:
    """All tuneable parameters in one place — override via CLI or constructor kwargs."""

    # ── Browser ───────────────────────────────────────────────────────────────
    headless: bool = True
    browser_timeout: int = 30_000        # ms
    page_load_timeout: int = 15_000      # ms

    # ── Google Maps ───────────────────────────────────────────────────────────
    maps_base_url: str = "https://www.google.com/maps/search/"
    scroll_count: int = 6                # times to scroll the results panel
    scroll_delay: float = 2.0            # seconds between scrolls
    result_click_delay: float = 1.5      # seconds to wait after navigating to a place

    # ── Rate limiting (seconds) ───────────────────────────────────────────────
    min_delay: float = 1.0
    max_delay: float = 3.0
    website_min_delay: float = 0.5
    website_max_delay: float = 1.5

    # ── Retry ─────────────────────────────────────────────────────────────────
    max_retries: int = 3
    retry_backoff: float = 2.0           # exponential backoff multiplier

    # ── Website scraping ──────────────────────────────────────────────────────
    contact_paths: list[str] = field(default_factory=lambda: [
        "/contact",
        "/contact-us",
        "/contactez-nous",
        "/nous-contacter",
        "/about",
        "/about-us",
        "/a-propos",
        "/qui-sommes-nous",
        "/equipe",
        "/team",
        "/our-team",
        "/mentions-legales",
        "/legal",
        "/legal-notice",
        "/impressum",
        "/imprint",
        "/coordonnees",
        "/infos",
    ])
    website_timeout: int = 10            # seconds per HTTP request

    # ── Description ───────────────────────────────────────────────────────────
    max_description_length: int = 300

    # ── Output ────────────────────────────────────────────────────────────────
    output_dir: str = "results"
    output_format: str = "both"          # "json" | "csv" | "both"

    # ── Concurrency ───────────────────────────────────────────────────────────
    max_concurrent_website_scrapers: int = 5

    # ── Quality filters ───────────────────────────────────────────────────────
    filter_junk: bool = True             # remove aggregator/directory results
    filter_empty: bool = True            # remove records with no enrichment data
    min_score: int = 0                   # keep only companies with score >= this

    # ── Enrichment ────────────────────────────────────────────────────────────
    address_backfill: bool = True        # re-query Google Maps for missing addresses

    # ── Stealth: realistic user-agent pool ────────────────────────────────────
    user_agents: list[str] = field(default_factory=lambda: [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
        "Gecko/20100101 Firefox/121.0",
    ])
