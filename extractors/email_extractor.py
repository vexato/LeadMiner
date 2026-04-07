"""Extract and deduplicate valid email addresses from arbitrary text or HTML."""

import re
from typing import Optional

from bs4 import BeautifulSoup

from utils.logger import setup_logger
from utils.validators import EMAIL_REGEX, is_valid_email

logger = setup_logger(__name__)


# Obfuscation patterns commonly used to hide emails from naive scrapers:
#   name [at] domain [dot] com
#   name (at) domain (dot) com
#   name AT domain DOT com
#   name {at} domain {dot} com
# Captures local, domain body, tld with the separators de-normalised.
_OBFUSCATED_RE = re.compile(
    r"""
    ([a-zA-Z0-9._%+\-]+)                     # local-part
    \s*(?:\[|\(|\{)?\s*(?:at|AT|At|arobase)\s*(?:\]|\)|\})?\s*
    ([a-zA-Z0-9\-]+(?:\s*(?:\[|\(|\{)?\s*(?:dot|DOT|Dot|point)\s*(?:\]|\)|\})?\s*[a-zA-Z0-9\-]+)+)
    """,
    re.VERBOSE,
)

# Matches "mailto:foo@bar.com" anywhere (href attributes *and* JS/script bodies)
_MAILTO_RE = re.compile(
    r"""mailto:\s*["']?\s*([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})""",
    re.IGNORECASE,
)


def _deobfuscate(match: re.Match) -> Optional[str]:
    """Turn a regex match on an obfuscated email into a clean 'local@domain' string."""
    local = match.group(1).strip()
    rest = match.group(2)
    # Normalise [dot]/(dot)/DOT/point → "."
    rest = re.sub(
        r"\s*(?:\[|\(|\{)?\s*(?:dot|DOT|Dot|point)\s*(?:\]|\)|\})?\s*",
        ".",
        rest,
    ).strip(".")
    if not rest or "." not in rest:
        return None
    return f"{local}@{rest}"


class EmailExtractor:
    """
    Email extractor with multiple strategies (in priority order):

      1. ``<a href="mailto:...">`` — most reliable signal.
      2. ``mailto:`` references embedded in any ``<script>`` body (JS).
      3. Obfuscated ``name [at] domain [dot] com`` patterns.
      4. Plain-text regex across the whole HTML as a fallback.

    Deduplicated per-instance; call ``reset()`` between companies if reused.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_from_text(self, text: str) -> list[str]:
        """Return all unique, valid emails found in plain *text*."""
        emails: list[str] = []
        for match in EMAIL_REGEX.findall(text):
            self._add(match, emails)
        return emails

    def extract_from_html(self, html: str) -> list[str]:
        """
        Parse *html* and return all unique, valid emails using every strategy.

        Order of strategies matters for ``extract_best``: mailto hrefs first,
        then JS mailtos, then obfuscated, then plain regex.
        """
        if not html:
            return []

        emails: list[str] = []

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception as exc:
            logger.debug(f"HTML parse failed, falling back to regex: {exc}")
            return self.extract_from_text(html)

        # 1. mailto: hrefs — highest signal
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.lower().startswith("mailto:"):
                # Strip any ?subject=... query params
                addr = href.split(":", 1)[1].split("?", 1)[0].strip()
                self._add(addr, emails)

        # 2. mailto: references inside <script> bodies (JS-obfuscated sites)
        for script in soup.find_all("script"):
            body = script.string or script.get_text() or ""
            if not body:
                continue
            for m in _MAILTO_RE.findall(body):
                self._add(m, emails)

        # Also look at the visible text for later stages
        visible = soup.get_text(separator=" ")

        # 3. obfuscated patterns (name [at] domain [dot] com, etc.)
        for m in _OBFUSCATED_RE.finditer(visible):
            candidate = _deobfuscate(m)
            if candidate:
                self._add(candidate, emails)

        # 4. Plain regex over visible text + any remaining mailto: references
        #    in the raw HTML (catches attributes we might have missed).
        for m in _MAILTO_RE.findall(html):
            self._add(m, emails)
        for m in EMAIL_REGEX.findall(visible):
            self._add(m, emails)

        return emails

    def extract_best(self, sources: list[str]) -> Optional[str]:
        """
        Return the first valid email found across multiple HTML sources.

        Each source is parsed with the full HTML strategy set; the first hit
        (in source order) wins.
        """
        for source in sources:
            results = self.extract_from_html(source)
            if results:
                return results[0]
        return None

    def reset(self) -> None:
        """Clear the seen-emails cache."""
        self._seen.clear()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _add(self, candidate: str, collector: list[str]) -> None:
        """Normalise, validate, dedupe, and append to *collector*."""
        email = candidate.lower().strip().rstrip(".,;:)]}>\"'")
        if not email or email in self._seen:
            return
        if is_valid_email(email):
            self._seen.add(email)
            collector.append(email)
            logger.debug(f"Found email: {email}")
