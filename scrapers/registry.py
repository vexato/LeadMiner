"""Resolve source names at CLI or engine boundaries."""

from pathlib import Path

from config.settings import Settings
from scrapers.base import BaseSource
from scrapers.catalog import CatalogSource
from scrapers.sirene import SireneSource

DEFAULT_SOURCE = "sirene"
LEGACY_SOURCES = ("maps", "pj", "google")
AVAILABLE_SOURCES = [DEFAULT_SOURCE, "catalog", *LEGACY_SOURCES]


def build_source(
    name: str, settings: Settings, *, catalog: Path | None = None, radius_km: float | None = None,
) -> BaseSource:
    if name == DEFAULT_SOURCE:
        return SireneSource(settings, radius_km)
    if name == "catalog":
        if catalog is None:
            raise ValueError("The catalog source requires --catalog")
        return CatalogSource(catalog)
    if name in LEGACY_SOURCES:
        if not settings.legacy_proxy:
            raise ValueError("Legacy sources require an authorized egress-filtering proxy")
        from scrapers.google_maps_scraper import GoogleMapsScraper
        from scrapers.google_search_scraper import GoogleSearchScraper
        from scrapers.pages_jaunes_scraper import PagesJaunesScraper

        return {"maps": GoogleMapsScraper, "pj": PagesJaunesScraper, "google": GoogleSearchScraper}[name](settings)
    raise ValueError(f"Unknown source {name}")


def parse_sources(raw: str) -> list[str]:
    names = list(dict.fromkeys(s.strip().lower() for s in raw.split(",") if s.strip()))
    if not names or set(names) - set(AVAILABLE_SOURCES):
        raise ValueError(f"Choose at least one source from {', '.join(AVAILABLE_SOURCES)}")
    return names
