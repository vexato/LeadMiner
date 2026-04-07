"""
Async website scraper that visits a company's homepage and common contact paths.

Returns raw HTML for each page so that the extractors (email, text) can
process them independently — the scraper itself has no extraction logic.
"""

import asyncio
from typing import Optional
from urllib.parse import urljoin, urlparse

import aiohttp

from config.settings import Settings
from utils.helpers import async_random_delay
from utils.logger import setup_logger
from utils.validators import is_valid_url

logger = setup_logger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}


class WebsiteScraper:
    """
    Fetches a company's homepage and the first reachable contact-like page.

    The caller supplies a shared `aiohttp.ClientSession` so that TCP
    connections are reused across multiple companies.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ── Public ────────────────────────────────────────────────────────────────

    async def scrape(
        self,
        url: str,
        session: aiohttp.ClientSession,
    ) -> dict[str, Optional[str]]:
        """
        Fetch the homepage and first reachable contact page.

        Args:
            url:     Normalised company website URL.
            session: Shared aiohttp session.

        Returns:
            Dict with keys:
              - ``homepage_html``    – HTML of the homepage (or None).
              - ``contact_page_url`` – URL of the first reached contact page.
              - ``contact_html``     – HTML of that first contact page.
              - ``extra_html``       – Concatenated HTML of up to
                                       ``MAX_EXTRA_PAGES - 1`` additional
                                       contact-like pages (legal, about, etc.),
                                       used to widen email extraction coverage.
        """
        result: dict[str, Optional[str]] = {
            "homepage_html": None,
            "contact_page_url": None,
            "contact_html": None,
            "extra_html": None,
        }

        if not is_valid_url(url):
            logger.debug(f"Skipping invalid URL: {url}")
            return result

        result["homepage_html"] = await self._fetch(session, url)

        # Walk every configured contact path and keep up to MAX_EXTRA_PAGES.
        # The FIRST hit is recorded as ``contact_page_url`` (exposed in results),
        # but subsequent pages are stacked into ``extra_html`` so the email
        # extractor still sees /mentions-legales, /a-propos, /impressum, etc.
        MAX_EXTRA_PAGES = 4
        extras: list[str] = []
        base = self._base(url)

        for path in self.settings.contact_paths:
            if len(extras) >= MAX_EXTRA_PAGES:
                break
            contact_url = urljoin(base, path)
            await async_random_delay(
                self.settings.website_min_delay,
                self.settings.website_max_delay,
            )
            html = await self._fetch(session, contact_url)
            if not html:
                continue
            if result["contact_page_url"] is None:
                result["contact_page_url"] = contact_url
                result["contact_html"] = html
                logger.debug(f"Contact page found: {contact_url}")
            extras.append(html)

        if len(extras) > 1:
            # The first page is already in contact_html; stack the rest.
            result["extra_html"] = "\n".join(extras[1:])

        return result

    # ── Private ───────────────────────────────────────────────────────────────

    async def _fetch(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        """GET *url* and return the response body as text, or None on error."""
        try:
            async with session.get(
                url,
                headers=_HEADERS,
                timeout=aiohttp.ClientTimeout(total=self.settings.website_timeout),
                allow_redirects=True,
                ssl=False,
            ) as resp:
                if resp.status == 200:
                    ct = resp.headers.get("Content-Type", "")
                    if "text/html" in ct or not ct:
                        return await resp.text(errors="replace")
                    logger.debug(f"Skipping non-HTML response ({ct}): {url}")
                else:
                    logger.debug(f"HTTP {resp.status}: {url}")
        except asyncio.TimeoutError:
            logger.debug(f"Timeout: {url}")
        except aiohttp.ClientError as exc:
            logger.debug(f"Client error ({exc}): {url}")
        except Exception as exc:
            logger.debug(f"Unexpected fetch error ({exc}): {url}")
        return None

    @staticmethod
    def _base(url: str) -> str:
        """Return scheme + netloc of *url*."""
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"
