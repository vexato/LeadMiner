"""
Enrichment pipeline: visits each company website and fills in email,
description, and contact_page fields using the website and extractors.

Runs website fetches concurrently (bounded by a semaphore) while the
Google Maps step is purely sequential inside the Playwright browser.
"""

import asyncio
from typing import Optional

import aiohttp

from config.settings import Settings
from extractors.email_extractor import EmailExtractor
from extractors.text_extractor import TextExtractor
from models.company import Company
from scrapers.website_scraper import WebsiteScraper
from utils.helpers import normalize_url
from utils.logger import setup_logger

logger = setup_logger(__name__)


class Pipeline:
    """
    Enriches a list of Company objects with data scraped from their websites.

    Steps per company (async, concurrent):
      1. Fetch homepage + contact page  (WebsiteScraper)
      2. Extract email                  (EmailExtractor)
      3. Extract description            (TextExtractor)
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.website_scraper = WebsiteScraper(settings)
        self.text_extractor = TextExtractor(settings.max_description_length)

    # ── Public ────────────────────────────────────────────────────────────────

    async def enrich_all(self, companies: list[Company]) -> list[Company]:
        """
        Enrich every company concurrently (up to ``max_concurrent_website_scrapers``).

        Args:
            companies: Companies discovered by the maps scraper.

        Returns:
            Same companies with email / description / contact_page filled in
            where possible.  Companies that fail enrichment are returned as-is.
        """
        if not companies:
            return companies

        semaphore = asyncio.Semaphore(self.settings.max_concurrent_website_scrapers)
        connector = aiohttp.TCPConnector(ssl=False, limit=20)

        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [
                self._bounded_enrich(company, session, semaphore)
                for company in companies
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        enriched: list[Company] = []
        for company, result in zip(companies, results):
            if isinstance(result, Exception):
                logger.warning(f"Enrichment failed for '{company.company_name}': {result}")
                enriched.append(company)
            else:
                enriched.append(result)  # type: ignore[arg-type]

        return enriched

    # ── Private ───────────────────────────────────────────────────────────────

    async def _bounded_enrich(
        self,
        company: Company,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
    ) -> Company:
        async with semaphore:
            return await self._enrich(company, session)

    async def _enrich(
        self,
        company: Company,
        session: aiohttp.ClientSession,
    ) -> Company:
        if not company.website:
            logger.debug(f"No website for '{company.company_name}' — skipping enrichment")
            return company

        url = normalize_url(company.website)
        logger.debug(f"Enriching: {company.company_name} ({url})")

        data = await self.website_scraper.scrape(url, session)

        homepage_html: str = data.get("homepage_html") or ""
        contact_html: str = data.get("contact_html") or ""
        contact_page_url: Optional[str] = data.get("contact_page_url")

        # Email: prefer contact page over homepage
        extractor = EmailExtractor()
        email = extractor.extract_best([contact_html, homepage_html])

        # Description: from homepage only
        description: Optional[str] = None
        if homepage_html:
            description = self.text_extractor.extract_description(homepage_html, url)

        return Company(
            company_name=company.company_name,
            website=url,
            email=email or company.email,
            # Keep scraped description if website enrichment found nothing
            description=description or company.description,
            contact_page=contact_page_url,
            address=company.address,
            sources=company.sources,   # preserve source tags
        )
