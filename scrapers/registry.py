"""
Source registry and factory.

To add a new source:
  1. Create ``scrapers/my_source.py`` extending BaseSource
  2. Import it here and add it to ``_REGISTRY``
  3. It becomes available via --source automatically
"""

from config.settings import Settings
from scrapers.base import BaseSource
from scrapers.google_maps_scraper import GoogleMapsScraper
from scrapers.google_search_scraper import GoogleSearchScraper
from scrapers.pages_jaunes_scraper import PagesJaunesScraper

_REGISTRY: dict[str, type[BaseSource]] = {
    "maps":   GoogleMapsScraper,
    "pj":     PagesJaunesScraper,
    "google": GoogleSearchScraper,
}

AVAILABLE_SOURCES = list(_REGISTRY)


def build_source(name: str, settings: Settings) -> BaseSource:
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown source '{name}'. Available: {', '.join(AVAILABLE_SOURCES)}"
        )
    return _REGISTRY[name](settings)


def parse_sources(raw: str) -> list[str]:
    """Validate and return a list of source names from a comma-separated string."""
    names = [s.strip().lower() for s in raw.split(",") if s.strip()]
    unknown = set(names) - set(AVAILABLE_SOURCES)
    if unknown:
        raise ValueError(
            f"Unknown source(s): {', '.join(sorted(unknown))}. "
            f"Available: {', '.join(AVAILABLE_SOURCES)}"
        )
    return names
