"""
Junk / noise filtering for company results.

Removes entries that are unlikely to be real companies:
aggregator websites, SEO list articles, or records with no
useful enrichment data at all.
"""

import urllib.parse
from typing import Optional

from models.company import Company
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Domains that aggregate or rank companies instead of being companies themselves
_JUNK_DOMAINS: frozenset[str] = frozenset([
    # Agency directories / comparators
    "sortlist.fr", "sortlist.be", "sortlist.com",
    "lafabriquedunet.fr",
    "clutch.co",
    "topagences.fr",
    "agence-web.pro",
    "annuaire-agence.fr",
    "web-agences.com",
    "les-meilleures-agences.com",
    "agences-france.fr",
    "agence.fr",
    # Freelance / job platforms
    "malt.fr",
    "codeur.com",
    "upwork.com",
    "freelance.com",
    "indeed.fr",
    "welcometothejungle.com",
    # Reviews / trust
    "trustpilot.com", "trustpilot.fr",
    "yelp.fr", "yelp.com",
    "avis-verifies.com",
    # Business registries (already filtered in scrapers but belt-and-suspenders)
    "pappers.fr", "societe.com", "verif.com",
    "infogreffe.fr", "manageo.fr", "kompass.com",
    "pagesjaunes.fr", "pagesbleues.fr",
    "annuaire.org", "118000.fr", "118712.fr",
    # Media / news
    "journaldunet.com", "01net.com", "bfmtv.com",
    # Maps / local directories
    "mappy.com",
    "tripadvisor.fr", "tripadvisor.com",
    # Classifieds
    "leboncoin.fr",
    # Social / aggregators (belt-and-suspenders)
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "linkedin.com", "youtube.com", "wikipedia.org",
    "google.com", "google.fr",
])

# Substrings in a company *name* that suggest it's a list/directory page
_JUNK_NAME_WORDS: frozenset[str] = frozenset([
    "top ",
    "meilleures",
    "meilleur",
    "comparatif",
    "classement",
    "les agences",
    " annuaire",
    "directory",
    "best ",
    "ranking",
])


def _domain(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        return urllib.parse.urlparse(url).netloc.lstrip("www.").lower() or None
    except Exception:
        return None


def _is_junk_domain(company: Company) -> bool:
    d = _domain(company.website)
    if not d:
        return False
    return any(d == junk or d.endswith("." + junk) for junk in _JUNK_DOMAINS)


def _is_junk_name(company: Company) -> bool:
    name_lower = company.company_name.lower()
    return any(word in name_lower for word in _JUNK_NAME_WORDS)


def _is_empty_record(company: Company) -> bool:
    """True when the record has no useful data beyond a name (no website, address, or enrichment)."""
    return (
        not company.website
        and not company.address
        and not company.email
        and not company.contact_page
        and not company.description
    )


def apply_junk_filter(
    companies: list[Company],
    *,
    filter_empty: bool = True,
) -> list[Company]:
    """
    Remove junk entries from *companies*.

    Three removal criteria:
    1. Known aggregator / directory domain
    2. Company name contains list/ranking keywords
    3. Record has no email, no contact page, and no description
       (only applied when ``filter_empty=True``)

    Args:
        companies:    Enriched company list.
        filter_empty: Remove records with zero enrichment data (default True).

    Returns:
        Filtered list of genuine company records.
    """
    kept: list[Company] = []
    dropped_domain = dropped_name = dropped_empty = 0

    for c in companies:
        if _is_junk_domain(c):
            logger.debug(f"Filter[domain]: dropped '{c.company_name}' ({c.website})")
            dropped_domain += 1
        elif _is_junk_name(c):
            logger.debug(f"Filter[name]: dropped '{c.company_name}'")
            dropped_name += 1
        elif filter_empty and _is_empty_record(c):
            logger.debug(f"Filter[empty]: dropped '{c.company_name}'")
            dropped_empty += 1
        else:
            kept.append(c)

    total_dropped = dropped_domain + dropped_name + dropped_empty
    if total_dropped:
        logger.info(
            f"Junk filter: {len(kept)} kept, {total_dropped} dropped "
            f"(domain={dropped_domain} name={dropped_name} empty={dropped_empty})"
        )
    return kept
