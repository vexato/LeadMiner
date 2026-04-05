"""
Google Search scraper — uses Playwright with stealth setup.

Extracts organic results: title → company name, URL → website,
snippet → description. Known aggregator domains are filtered out.
"""

import asyncio
import random
import urllib.parse
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from config.settings import Settings
from models.company import Company
from scrapers.base import BaseSource
from utils.helpers import async_random_delay
from utils.logger import setup_logger

logger = setup_logger(__name__)

_SEARCH_URL = "https://www.google.fr/search?q={query}&hl=fr&num=20"

_SKIP_DOMAINS = frozenset([
    "pagesjaunes.fr", "pagesbleues.fr", "societe.com", "verif.com",
    "infogreffe.fr", "pappers.fr", "manageo.fr", "kompass.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "linkedin.com", "youtube.com", "wikipedia.org",
    "google.com", "google.fr", "tripadvisor.fr",
    "leboncoin.fr", "indeed.fr", "welcometothejungle.com",
    "annuaire.org", "118000.fr", "118712.fr",
])


class GoogleSearchScraper(BaseSource):
    """
    Discovers companies via Google Search organic results.

    Each result gives: title (→ company name), URL (→ website),
    snippet (→ description). Lighter than Maps: no per-place navigation.
    """

    name = "google"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ── Public ────────────────────────────────────────────────────────────────

    async def search(self, query: str, location: str, limit: int) -> list[Company]:
        search_term = f"{query} {location}"
        logger.info(f"Google Search: '{search_term}' (limit={limit})")

        async with async_playwright() as pw:
            browser = await self._launch(pw)
            context = await self._context(browser)
            page = await context.new_page()
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            try:
                companies = await self._run(page, search_term, limit)
            except Exception as exc:
                logger.error(f"Google Search failed: {exc}")
                companies = []
            finally:
                await browser.close()

        logger.info(f"Google Search: {len(companies)} companies found")
        return companies

    # ── Browser setup ─────────────────────────────────────────────────────────

    async def _launch(self, pw) -> Browser:
        return await pw.chromium.launch(
            headless=self.settings.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--window-size=1366,768",
            ],
        )

    async def _context(self, browser: Browser) -> BrowserContext:
        return await browser.new_context(
            user_agent=random.choice(self.settings.user_agents),
            viewport={"width": 1366, "height": 768},
            locale="fr-FR",
            timezone_id="Europe/Paris",
            extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
        )

    # ── Search workflow ───────────────────────────────────────────────────────

    async def _run(self, page: Page, search_term: str, limit: int) -> list[Company]:
        encoded = urllib.parse.quote_plus(search_term)
        await page.goto(
            _SEARCH_URL.format(query=encoded),
            wait_until="domcontentloaded",
            timeout=self.settings.browser_timeout,
        )
        await self._dismiss_consent(page)
        await asyncio.sleep(1.0)

        companies: list[Company] = []
        page_num = 0
        max_pages = max(3, limit // 10 + 1)

        while len(companies) < limit and page_num < max_pages:
            batch = await self._extract_results(page)
            if not batch:
                logger.debug(f"Google Search: no results on page {page_num + 1}")
                break

            companies.extend(batch)
            logger.debug(
                f"  Page {page_num + 1}: +{len(batch)} results (total {len(companies)})"
            )
            page_num += 1

            if len(companies) < limit:
                if not await self._next_page(page):
                    break
                await async_random_delay(self.settings.min_delay, self.settings.max_delay)

        return companies[:limit]

    async def _dismiss_consent(self, page: Page) -> None:
        for sel in (
            "#L2AGLb",
            'button:has-text("Tout accepter")',
            'button:has-text("Accept all")',
            '[aria-label="Tout accepter"]',
        ):
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2_000):
                    await btn.click()
                    await asyncio.sleep(1.0)
                    return
            except Exception:
                continue

    # ── Result extraction ─────────────────────────────────────────────────────

    async def _extract_results(self, page: Page) -> list[Company]:
        """
        Extract organic results using a robust JS approach:
        find all <h3> inside the page, climb to the parent <a> to get the URL,
        then look for a nearby snippet.  Avoids fragile class-name selectors.
        """
        try:
            raw: list[dict] = await page.evaluate("""
                () => {
                    const results = [];
                    document.querySelectorAll('h3').forEach(h3 => {
                        // Walk up to find the enclosing <a>
                        let a = h3.closest('a');
                        if (!a) {
                            a = h3.parentElement && h3.parentElement.closest('a');
                        }
                        if (!a) return;
                        const href = a.href;
                        if (!href || !href.startsWith('http')) return;
                        // Skip Google's own UI links
                        if (href.includes('google.') && !href.includes('url=')) return;

                        // Look for snippet text near the result block
                        const block = h3.closest('[data-hveid]') ||
                                      h3.closest('div.g') ||
                                      h3.parentElement?.parentElement?.parentElement;
                        let snippet = '';
                        if (block) {
                            const snEl = block.querySelector(
                                '[data-sncf], .VwiC3b, .yXK7lf, span[style*="webkit"]'
                            );
                            snippet = snEl ? snEl.innerText.trim() : '';
                        }
                        results.push({
                            href: href,
                            title: h3.innerText.trim(),
                            snippet: snippet,
                        });
                    });
                    return results;
                }
            """)
        except Exception as exc:
            logger.debug(f"Google Search JS extraction error: {exc}")
            return []

        companies: list[Company] = []
        seen_domains: set[str] = set()

        for item in raw:
            company = self._to_company(item, seen_domains)
            if company:
                companies.append(company)

        return companies

    def _to_company(self, item: dict, seen_domains: set[str]) -> Optional[Company]:
        href: str = item.get("href", "")
        title: str = item.get("title", "").strip()
        snippet: str = item.get("snippet", "").strip()

        if not href.startswith("http") or not title:
            return None

        domain = urllib.parse.urlparse(href).netloc.lstrip("www.")

        # Skip aggregators
        if any(domain.endswith(d) for d in _SKIP_DOMAINS):
            return None

        # One result per domain
        if domain in seen_domains:
            return None
        seen_domains.add(domain)

        # Clean common title suffixes
        for suffix in (
            " - site officiel", " – site officiel",
            " | accueil", " - accueil", " | bienvenue",
        ):
            if title.lower().endswith(suffix.lower()):
                title = title[: -len(suffix)].strip()

        description: Optional[str] = snippet or None
        if description and len(description) > self.settings.max_description_length:
            description = description[: self.settings.max_description_length].rsplit(" ", 1)[0] + "…"

        return Company(company_name=title, website=href, description=description)

    # ── Pagination ────────────────────────────────────────────────────────────

    async def _next_page(self, page: Page) -> bool:
        try:
            btn = page.locator('#pnnext, a[aria-label="Page suivante"], a[aria-label="Next"]').first
            if await btn.is_visible(timeout=3_000):
                await btn.click()
                await page.wait_for_load_state("domcontentloaded")
                return True
        except Exception:
            pass
        return False
