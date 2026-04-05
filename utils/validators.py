"""Input and output validation helpers."""

import re
from typing import Optional
from urllib.parse import urlparse


EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

# Domains that appear in code/templates but are not real contact emails
_GENERIC_DOMAINS = frozenset([
    "example.com", "test.com", "email.com", "domain.com",
    "sentry.io", "wixpress.com", "w3.org", "schema.org",
    "yourdomain.com", "yoursite.com",
])

# Image-like suffixes that regex can accidentally match
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


def is_valid_url(url: str) -> bool:
    """Return True if *url* is an absolute HTTP(S) URL."""
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def is_valid_email(email: str) -> bool:
    """Return True if *email* passes format checks and is not obviously fake."""
    if not EMAIL_REGEX.fullmatch(email):
        return False

    domain = email.split("@")[-1].lower()
    if domain in _GENERIC_DOMAINS:
        return False

    if any(email.lower().endswith(ext) for ext in _IMAGE_EXTS):
        return False

    return True


def extract_domain(url: str) -> Optional[str]:
    """Return the netloc of *url*, or None on failure."""
    try:
        return urlparse(url).netloc or None
    except Exception:
        return None
