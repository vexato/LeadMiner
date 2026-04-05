"""Post-enrichment company filtering by required fields."""

from models.company import Company
from utils.logger import setup_logger

logger = setup_logger(__name__)

# CLI keyword → Company attribute
FIELD_MAP: dict[str, str] = {
    "email":       "email",
    "contact":     "contact_page",
    "website":     "website",
    "address":     "address",
    "description": "description",
}

VALID_FIELDS = set(FIELD_MAP)


def parse_only(raw: str) -> list[str]:
    """
    Parse the --only argument into a validated list of field names.

    Args:
        raw: Comma-separated string, e.g. "email,contact".

    Returns:
        List of lowercased, validated field names.

    Raises:
        ValueError: If any token is not a recognised field name.
    """
    tokens = [t.strip().lower() for t in raw.split(",") if t.strip()]
    unknown = set(tokens) - VALID_FIELDS
    if unknown:
        raise ValueError(
            f"Unknown --only field(s): {', '.join(sorted(unknown))}. "
            f"Valid options: {', '.join(sorted(VALID_FIELDS))}"
        )
    return tokens


def apply_only(companies: list[Company], fields: list[str]) -> list[Company]:
    """
    Keep only companies that have *all* of the specified fields populated.

    Args:
        companies: Enriched company list.
        fields:    Field names returned by ``parse_only()``.

    Returns:
        Filtered list (empty fields mean the company is excluded).
    """
    if not fields:
        return companies

    attrs = [FIELD_MAP[f] for f in fields]

    def passes(c: Company) -> bool:
        return all(bool(getattr(c, attr, None)) for attr in attrs)

    kept = [c for c in companies if passes(c)]
    dropped = len(companies) - len(kept)

    label = " + ".join(fields)
    logger.info(
        f"Filter [{label}]: {len(kept)} kept, {dropped} dropped"
        f" (had no {' / '.join(fields)})"
    )
    return kept
