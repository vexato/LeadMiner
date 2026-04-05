"""Extract a short, meaningful description from a company webpage."""

import re
from typing import Optional

from bs4 import BeautifulSoup

from utils.logger import setup_logger

logger = setup_logger(__name__)

# CSS selectors tried in order to locate the main content block
_CONTENT_SELECTORS = [
    "main",
    "article",
    '[role="main"]',
    "#content",
    ".content",
    ".main-content",
    "#main",
    "section",
]

# Lowercase phrases that indicate boilerplate rather than real description
_BOILERPLATE = [
    "cookie", "accept", "privacy policy", "terms of service",
    "all rights reserved", "nous utilisons des cookies",
    "accepter", "refuser", "mentions légales", "cliquez ici",
]


class TextExtractor:
    """
    Extract a concise description from raw HTML.

    Priority order:
      1. <meta name="description"> / <meta property="og:description">
      2. First meaningful content block found via CSS selectors
      3. <body> text as fallback
    """

    def __init__(self, max_length: int = 300) -> None:
        self.max_length = max_length

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_description(self, html: str, url: str = "") -> Optional[str]:
        """
        Parse *html* and return a clean summary string.

        Args:
            html: Raw HTML content of the page.
            url:  Page URL (used for logging only).

        Returns:
            Truncated description string, or None if nothing meaningful found.
        """
        try:
            soup = BeautifulSoup(html, "lxml")

            # 1. Meta description (usually the best single-line summary)
            meta = self._meta_description(soup)
            if meta and len(meta) > 20:
                return self._truncate(meta)

            # 2. Identified content blocks
            body_text = self._content_block(soup)
            if body_text:
                return self._truncate(body_text)

            # 3. Full body fallback
            body = soup.find("body")
            if body:
                raw = body.get_text(separator=" ")
                cleaned = self._clean(raw)
                return self._truncate(cleaned) if cleaned else None

        except Exception as exc:
            logger.debug(f"Description extraction failed for {url}: {exc}")

        return None

    # ── Private helpers ───────────────────────────────────────────────────────

    def _meta_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Try <meta name="description"> then og:description."""
        for attrs in ({"name": "description"}, {"property": "og:description"}):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    def _content_block(self, soup: BeautifulSoup) -> Optional[str]:
        """Try each content selector and return the first non-trivial block."""
        for selector in _CONTENT_SELECTORS:
            el = soup.select_one(selector)
            if el:
                text = self._clean(el.get_text(separator=" "))
                if len(text) > 50:
                    return text
        return None

    def _clean(self, raw: str) -> str:
        """Collapse whitespace and strip boilerplate sentences."""
        text = re.sub(r"\s+", " ", raw).strip()
        sentences = [s.strip() for s in text.split(".") if s.strip()]
        kept = [s for s in sentences if not any(bp in s.lower() for bp in _BOILERPLATE)]
        return ". ".join(kept).strip()

    def _truncate(self, text: str) -> str:
        """Cut *text* to max_length at a word boundary."""
        if len(text) <= self.max_length:
            return text
        cut = text[: self.max_length].rsplit(" ", 1)[0]
        return cut.rstrip(".,;:") + "…"
