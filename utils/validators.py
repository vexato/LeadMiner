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
    # Standard placeholder/example domains
    "example.com", "example.org", "example.net",
    "test.com", "test.org", "testing.com",
    "email.com", "domain.com", "mydomain.com",
    "yourdomain.com", "your-domain.com",
    "yoursite.com", "your-site.com",
    "yourcompany.com", "your-company.com",
    "mycompany.com", "my-company.com",
    "company.com", "company.fr",
    "website.com", "yourwebsite.com",
    "sample.com", "demo.com",
    "foo.com", "bar.com",
    "lorem.com", "ipsum.com",
    # SaaS / platform internals that leak into pages
    "sentry.io", "wixpress.com",
    "w3.org", "schema.org",
    "wordpress.com", "wordpress.org",
    "squarespace.com",
])

# Local-part prefixes that scream "placeholder"
_PLACEHOLDER_LOCAL_PARTS = frozenset([
    "votre.email", "votre.adresse", "votre.nom", "votre-email",
    "your.email", "your.name", "your-email", "your-name",
    "name", "nom", "email", "youremail", "votreemail",
    "firstname.lastname", "prenom.nom",
    "user", "username", "utilisateur",
    "exemple", "example", "sample", "demo",
])

# Email local-parts that contain these substrings are almost always placeholders
_PLACEHOLDER_LOCAL_SUBSTRINGS = (
    "yourcompany", "your-company",
    "yourdomain", "your-domain",
    "yoursite", "your-site",
    "yourname", "your-name",
    "yourmail", "your-mail",
    "mycompany", "my-company",
    "mydomain", "my-domain",
    "placeholder",
)

# Free / consumer email providers — kept but penalised in scoring
_FREE_EMAIL_PROVIDERS = frozenset([
    "gmail.com", "googlemail.com",
    "yahoo.com", "yahoo.fr",
    "hotmail.com", "hotmail.fr",
    "outlook.com", "outlook.fr",
    "live.com", "live.fr",
    "msn.com",
    "aol.com",
    "icloud.com", "me.com", "mac.com",
    "protonmail.com", "proton.me", "pm.me",
    "orange.fr", "wanadoo.fr",
    "free.fr",
    "sfr.fr", "neuf.fr",
    "laposte.net",
    "bbox.fr",
    "gmx.com", "gmx.fr", "gmx.net",
    "yandex.com", "yandex.ru",
    "mail.com",
    "zoho.com",
])

# Image-like suffixes that regex can accidentally match
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico")


def is_valid_url(url: str) -> bool:
    """Return True if *url* is an absolute HTTP(S) URL."""
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def is_valid_email(email: str) -> bool:
    """Return True if *email* passes format checks and is not an obvious placeholder."""
    if not EMAIL_REGEX.fullmatch(email):
        return False

    email_lower = email.lower()
    local, _, domain = email_lower.partition("@")

    if domain in _GENERIC_DOMAINS:
        return False

    if local in _PLACEHOLDER_LOCAL_PARTS:
        return False

    if any(s in local for s in _PLACEHOLDER_LOCAL_SUBSTRINGS):
        return False

    # "info@company", "contact@company" with no TLD-like suffix that makes sense
    # is caught by _GENERIC_DOMAINS (company.com/company.fr).  Also catch the
    # bare "@company" pattern defensively in case the regex admits it.
    if domain in ("company", "yourcompany", "mycompany", "domain", "example"):
        return False

    if any(email_lower.endswith(ext) for ext in _IMAGE_EXTS):
        return False

    return True


def is_free_email_provider(email: str) -> bool:
    """Return True if *email* belongs to a consumer/free email provider."""
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in _FREE_EMAIL_PROVIDERS


def extract_domain(url: str) -> Optional[str]:
    """Return the netloc of *url*, or None on failure."""
    try:
        return urlparse(url).netloc or None
    except Exception:
        return None
