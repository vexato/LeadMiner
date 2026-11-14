import asyncio
import unicodedata
import urllib.parse

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from config.settings import Settings
from models.company import Company
from scrapers.base import BaseSource, SourceError
from utils.helpers import async_random_delay
from utils.logger import setup_logger

logger = setup_logger(__name__)

_SEARCH_URL = (
    "https://www.pagesjaunes.fr/annuaire/chercherlespros"
    "?quoiqui={quoiqui}&ou={ou}&univers=pagesjaunes&idOu=&page={page}"
)


def _location_slug(location: str) -> str:
    """
    Convert a city name to the PJ location slug format.
    e.g. "Bordeaux" → "bordeaux", "Île-de-France" → "ile-de-france"
    """
    # Strip accents
    nfd = unicodedata.normalize("NFD", location)
    ascii_str = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return ascii_str.lower().strip().replace(" ", "-")


class PagesJaunesScraper(BaseSource):
    """Discovers companies via pagesjaunes.fr search using Playwright."""

    name = "pj"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ── Public ────────────────────────────────────────────────────────────────

    async def search(self, query: str, location: str, limit: int) -> list[Company]:
        logger.info(f"Pages Jaunes search: '{query}' in '{location}' (limit={limit})")

        async with async_playwright() as pw:
            browser = await self._launch(pw)
            context = await self._context(browser)
            page = await context.new_page()
            try:
                companies = await self._run(page, query, location, limit)
            except Exception as exc:
                raise SourceError("pj_browser_error") from exc
            finally:
                await browser.close()

        logger.info(f"Pages Jaunes: {len(companies)} companies found")
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
            viewport={"width": 1366, "height": 768},
            locale="fr-FR",
            timezone_id="Europe/Paris",
            extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9"},
        )

    # ── Search workflow ───────────────────────────────────────────────────────

    async def _run(self, page: Page, query: str, location: str, limit: int) -> list[Company]:
        # ── One-time: dismiss consent on the homepage so the SPA boots cleanly ──
        await page.goto("https://www.pagesjaunes.fr/", wait_until="load",
                        timeout=self.settings.browser_timeout)
        await asyncio.sleep(2.5)
        await self._dismiss_consent(page)
        await asyncio.sleep(1.0)
        logger.debug(f"PJ: consent handled on homepage (title='{await page.title()}')")

        # ── Step 1: collect raw cards (name + PJ profile URL) from search pages ──
        raw_cards: list[dict] = []
        pj_page = 1

        while len(raw_cards) < limit:
            url = _SEARCH_URL.format(
                quoiqui=urllib.parse.quote_plus(query),
                ou=urllib.parse.quote_plus(_location_slug(location)),
                page=pj_page,
            )
            await page.goto(url, wait_until="networkidle", timeout=self.settings.browser_timeout)
            await asyncio.sleep(1.5)

            title = await page.title()
            logger.debug(f"PJ search page {pj_page}: title='{title}'")

            if any(kw in title.lower() for kw in ("just a moment", "access denied", "403", "captcha")):
                raise SourceError("pj_access_restricted")

            batch = await self._scrape_search_page(page)
            if not batch:
                logger.info(f"PJ: no cards found on search page {pj_page} — stopping")
                break

            raw_cards.extend(batch)
            logger.debug(f"PJ: search page {pj_page} → +{len(batch)} cards (total {len(raw_cards)})")
            pj_page += 1

            if len(raw_cards) < limit:
                await async_random_delay(self.settings.min_delay, self.settings.max_delay)

        raw_cards = raw_cards[:limit]

        return [Company(company_name=card["name"], address=card.get("address"))
                for card in raw_cards]

    async def _dismiss_consent(self, page: Page) -> None:
        """Dismiss cookie/consent overlay if present."""
        for sel in (
            '#didomi-notice-agree-button',
            'button:has-text("Accepter")',
            'button:has-text("Tout accepter")',
            '[aria-label*="accepter"]',
        ):
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2_000):
                    await btn.click()
                    await asyncio.sleep(0.8)
                    return
            except Exception:
                continue

    # ── Google website discovery ───────────────────────────────────────────────

    async def _scrape_search_page(self, page: Page) -> list[dict]:
        """
        Extract raw card data from a PJ search results page.
        Returns list of {name, address} dicts.
        """
        try:
            raw: list[dict] = await page.evaluate(r"""
                () => {
                    const results = [];
                    const seen = new Set();
                    document.querySelectorAll('li').forEach(el => {
                        const heading = el.querySelector('h2 a, h3 a, h2, h3');
                        if (!heading) return;
                        const name = heading.innerText.trim();
                        if (!name || name.length < 2) return;


                        const addrEl = (
                            el.querySelector('[class*="adresse"]') ||
                            el.querySelector('[class*="address"]') ||
                            el.querySelector('[class*="localisation"]') ||
                            el.querySelector('address')
                        );
                        // Clone + strip <a> links (e.g. "Voir le plan") before reading text
                        let address = null;
                        if (addrEl) {
                            const clone = addrEl.cloneNode(true);
                            clone.querySelectorAll('a').forEach(a => a.remove());
                            address = clone.innerText.replace(/\s+/g, ' ').trim() || null;
                        }

                        const key = JSON.stringify([name, address]);
                        if (seen.has(key)) return;
                        seen.add(key);
                        results.push({ name, address });
                    });
                    return results;
                }
            """)
        except Exception as exc:
            logger.debug(f"PJ search page extraction error: {exc}")
            return []
        return raw


