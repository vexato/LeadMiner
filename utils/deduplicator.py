"""
Company deduplication with field merging.

Matches duplicates by normalized company name OR website domain.
When a match is found, fields are merged — keeping the richest data
from each source rather than discarding the weaker record.
"""

import re
import urllib.parse
from typing import Optional

from models.company import Company
from utils.logger import setup_logger

logger = setup_logger(__name__)

_SUFFIX_RE = re.compile(
    r"\b(sarl|sas|sa|eurl|sci|snc|ltd|llc|inc|gmbh|bv|nv|spa|oy)\b",
    re.IGNORECASE,
)


def _norm_name(name: str) -> str:
    """Lowercase, strip legal suffixes and punctuation."""
    name = name.lower().strip()
    name = _SUFFIX_RE.sub("", name)
    name = re.sub(r"[^\w\s]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _extract_domain(url: Optional[str]) -> Optional[str]:
    """Return bare domain (no www) from a URL, or None on failure."""
    if not url:
        return None
    try:
        return urllib.parse.urlparse(url).netloc.lstrip("www.").lower() or None
    except Exception:
        return None


def _merge(a: Company, b: Company) -> Company:
    """
    Merge two Company records, keeping the richest field from each.

    *a* wins on ties (name, website).  The ``score`` field is reset to 0
    so it can be recalculated after merging.
    """
    # Keep the longer description
    if a.description and b.description:
        desc = a.description if len(a.description) >= len(b.description) else b.description
    else:
        desc = a.description or b.description

    merged_sources = sorted(set((a.sources or []) + (b.sources or [])))

    return Company(
        company_name=a.company_name or b.company_name,
        website=a.website or b.website,
        email=a.email or b.email,
        description=desc,
        contact_page=a.contact_page or b.contact_page,
        address=a.address or b.address,
        sources=merged_sources,
        score=0,
    )


def deduplicate(companies: list[Company]) -> list[Company]:
    """
    Remove duplicate companies, merging their fields.

    Duplicate detection uses two signals (either is sufficient):
    - Normalised company name (lowercased, legal suffixes stripped)
    - Website domain (exact match after stripping ``www.``)

    Domain matching takes precedence over name matching when both apply.

    Args:
        companies: Raw list, potentially containing duplicates.

    Returns:
        Deduplicated list with fields merged from all matching records.
    """
    result: list[Company] = []
    seen_names: dict[str, int] = {}    # norm_name → index in result
    seen_domains: dict[str, int] = {}  # domain    → index in result

    for company in companies:
        domain = _extract_domain(company.website)
        norm = _norm_name(company.company_name)

        # Domain match has priority (more reliable than name)
        idx: Optional[int] = None
        if domain and domain in seen_domains:
            idx = seen_domains[domain]
        elif norm and norm in seen_names:
            idx = seen_names[norm]

        if idx is not None:
            result[idx] = _merge(result[idx], company)
            # Make sure both signatures map to the same slot
            seen_names[norm] = idx
            if domain:
                seen_domains[domain] = idx
        else:
            idx = len(result)
            result.append(company)
            if norm:
                seen_names[norm] = idx
            if domain:
                seen_domains[domain] = idx

    removed = len(companies) - len(result)
    logger.debug(f"Deduplicator: {len(companies)} → {len(result)} companies ({removed} merged)")
    return result
