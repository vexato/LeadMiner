"""Extract and deduplicate valid email addresses from arbitrary text or HTML."""

from typing import Optional

from utils.logger import setup_logger
from utils.validators import EMAIL_REGEX, is_valid_email

logger = setup_logger(__name__)


class EmailExtractor:
    """
    Regex-based email extractor with per-instance deduplication.

    Create one instance per company run and call `reset()` between companies
    if you reuse the instance across multiple calls.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_from_text(self, text: str) -> list[str]:
        """
        Return all unique, valid emails found in *text*.

        Args:
            text: Raw text or HTML content.

        Returns:
            Ordered list of valid email strings (lowercase).
        """
        emails: list[str] = []
        for match in EMAIL_REGEX.findall(text):
            candidate = match.lower().strip()
            if is_valid_email(candidate) and candidate not in self._seen:
                self._seen.add(candidate)
                emails.append(candidate)
                logger.debug(f"Found email: {candidate}")
        return emails

    def extract_best(self, sources: list[str]) -> Optional[str]:
        """
        Return the first valid email found across multiple text sources.

        Pass sources in descending priority order
        (e.g., contact page HTML first, then homepage HTML).

        Args:
            sources: List of text/HTML strings ordered by priority.

        Returns:
            The highest-priority email, or None if nothing found.
        """
        for text in sources:
            results = self.extract_from_text(text)
            if results:
                return results[0]
        return None

    def reset(self) -> None:
        """Clear the seen-emails cache."""
        self._seen.clear()
