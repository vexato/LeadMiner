"""
Google Maps scraper using Playwright.

Searches for "{query} {location}", scrolls the results panel to collect
place URLs, then visits each place page to extract name, address, and
website.  Basic stealth measures (realistic UA, disabled automation flags,
random delays) are applied to reduce the risk of bot detection.

To swap this source for another (e.g. Yelp, Societe.com), implement the
same `search(query, location, limit) -> list[Company]` interface.
"""

import asyncio
import random
import urllib.parse
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

from config.settings import Settings
from models.company import Company
from scrapers.base import BaseSource
from utils.helpers import async_random_delay
from utils.logger import setup_logger

logger = setup_logger(__name__)


class GoogleMapsScraper(BaseSource):
    """
    Discovers companies via Google Maps search.

    Implements BaseSource — swap with any other source without touching
    the pipeline.
    """

    name = "google_maps"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ── Public ────────────────────────────────────────────────────────────────

    async def search(self, query: str, location: str, limit: int) -> list[Company]:
        """
        Run a Google Maps search and return up to *limit* companies.

        Args:
            query:    Domain to search (e.g. "web development").
            location: Geographic filter (e.g. "Bordeaux").
            limit:    Maximum number of results.

        Returns:
            List of Company objects populated with name, address, and
            website (email/description are filled later in the pipeline).
        """
        search_term = f"{query} {location}"
        encoded = urllib.parse.quote_plus(search_term)
        url = f"{self.settings.maps_base_url}{encoded}"

        logger.info(f"Google Maps search: '{search_term}' (limit={limit})")

        async with async_playwright() as pw:
            browser = await self._launch_browser(pw)
            context = await self._create_context(browser)
            page = await context.new_page()

            # Prevent detection via navigator.webdriver
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            try:
                return await self._run_search(page, url, limit)
            except Exception as exc:
                logger.error(f"Google Maps search failed: {exc}")
                return []
            finally:
                await browser.close()

    # ── Browser setup ─────────────────────────────────────────────────────────

    async def _launch_browser(self, pw) -> Browser:
        return await pw.chromium.launch(
            headless=self.settings.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--window-size=1366,768",
            ],
        )

    async def _create_context(self, browser: Browser) -> BrowserContext:
        ua = random.choice(self.settings.user_agents)
        return await browser.new_context(
            user_agent=ua,
            viewport={"width": 1366, "height": 768},
            locale="fr-FR",
            timezone_id="Europe/Paris",
            extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
        )

    # ── Search workflow ───────────────────────────────────────────────────────

    async def _run_search(self, page: Page, url: str, limit: int) -> list[Company]:
        await page.goto(
            url,
            timeout=self.settings.browser_timeout,
            wait_until="domcontentloaded",
        )
        await self._dismiss_consent(page)

        # Wait for the results feed to appear
        try:
            await page.wait_for_selector('[role="feed"]', timeout=12_000)
        except Exception:
            logger.warning("Results feed selector not found — page structure may have changed")

        place_urls = await self._collect_place_urls(page, limit)
        if not place_urls:
            logger.warning("No place URLs collected — check selectors or try non-headless mode")
            return []

        logger.info(f"Collected {len(place_urls)} place URLs; visiting each…")

        companies: list[Company] = []
        for idx, place_url in enumerate(place_urls[:limit], 1):
            logger.debug(f"  [{idx}/{min(len(place_urls), limit)}] {place_url}")
            company = await self._extract_place(page, place_url)
            if company:
                companies.append(company)
            await async_random_delay(self.settings.min_delay, self.settings.max_delay)

        logger.info(f"Google Maps: extracted {len(companies)} companies")
        return companies

    async def _dismiss_consent(self, page: Page) -> None:
        """Click through Google's GDPR consent overlay if present."""
        selectors = [
            "#L2AGLb",                          # classic "Accept all" button id
            'button:has-text("Tout accepter")',
            'button:has-text("Accept all")',
            '[aria-label="Tout accepter"]',
            '[aria-label="Accept all"]',
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2_000):
                    await btn.click()
                    await asyncio.sleep(1.0)
                    logger.debug("Consent overlay dismissed")
                    return
            except Exception:
                continue

    async def _collect_place_urls(self, page: Page, limit: int) -> list[str]:
        """
        Scroll the results panel until *limit* URLs are collected or Google
        Maps has no more results to show.

        Termination conditions (whichever comes first):
          - ``len(seen) >= limit``
          - 3 consecutive scrolls that add zero new URLs  (end of results)
          - Hard cap of ``max(scroll_count, limit // 3 + 10)`` scrolls
        """
        seen: set[str] = set()
        max_scrolls = max(self.settings.scroll_count, limit // 3 + 10)
        stale = 0          # consecutive scrolls with no new URLs
        MAX_STALE = 3

        for i in range(max_scrolls):
            prev = len(seen)
            try:
                links: list[str] = await page.eval_on_selector_all(
                    'a[href*="/maps/place/"]',
                    "els => els.map(el => el.href)",
                )
                seen.update(links)
            except Exception as exc:
                logger.debug(f"  Link collection error on scroll {i}: {exc}")

            added = len(seen) - prev
            logger.debug(
                f"  Scroll {i + 1}/{max_scrolls}: +{added} new  (total {len(seen)}/{limit})"
            )

            if len(seen) >= limit:
                logger.debug("  Limit reached — stopping scroll")
                break

            if added == 0:
                stale += 1
                if stale >= MAX_STALE:
                    logger.info(
                        f"  No new results for {MAX_STALE} scrolls — "
                        f"Google Maps has ~{len(seen)} results for this query"
                    )
                    break
            else:
                stale = 0

            # Scroll the left-hand results panel
            try:
                await page.eval_on_selector(
                    '[role="feed"]',
                    "el => el.scrollBy(0, 900)",
                )
            except Exception:
                await page.keyboard.press("End")

            await asyncio.sleep(self.settings.scroll_delay)

        return list(seen)

    # ── Place detail extraction ───────────────────────────────────────────────

    async def _extract_place(self, page: Page, url: str) -> Optional[Company]:
        """Navigate to a place page and extract structured fields."""
        try:
            await page.goto(
                url,
                timeout=self.settings.browser_timeout,
                wait_until="domcontentloaded",
            )
            await asyncio.sleep(self.settings.result_click_delay)

            name = await self._get_text(page, [
                "h1.DUwDvf",
                'h1[data-attrid="title"]',
                "h1",
            ])
            if not name:
                logger.debug(f"Could not extract name from {url}")
                return None

            address = await self._get_text(page, [
                'button[data-item-id="address"] .fontBodyMedium',
                '[data-item-id="address"]',
                'button[aria-label*="Adresse"] .fontBodyMedium',
                'button[aria-label*="Address"] .fontBodyMedium',
            ])

            website = await self._get_href(page, [
                'a[data-item-id="authority"]',
                'a[aria-label*="site web"]',
                'a[aria-label*="website"]',
                'a[data-tooltip*="site"]',
            ])

            return Company(
                company_name=name.strip(),
                website=website,
                address=address.strip() if address else None,
            )

        except Exception as exc:
            logger.debug(f"Error extracting place data: {exc}")
            return None

    async def _get_text(self, page: Page, selectors: list[str]) -> Optional[str]:
        """Try selectors in order and return the first non-empty inner text."""
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2_000):
                    text = await el.inner_text()
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue
        return None

    async def _get_href(self, page: Page, selectors: list[str]) -> Optional[str]:
        """Try selectors in order and return the first valid href."""
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2_000):
                    href = await el.get_attribute("href")
                    if href and href.startswith("http"):
                        return href
            except Exception:
                continue
        return None
