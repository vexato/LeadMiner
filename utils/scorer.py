"""
Quality scoring for Company objects.

Each company receives a numeric score based on which fields are populated.
Higher score = more complete, higher-quality result.
Results are sorted by score (descending) before export.
"""

from models.company import Company
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Attribute name → points awarded when that field is present and non-empty
FIELD_WEIGHTS: dict[str, int] = {
    "website":      2,
    "email":        2,
    "contact_page": 1,
    "description":  1,
    "address":      1,
}

MAX_SCORE: int = sum(FIELD_WEIGHTS.values())  # 7


def score_company(company: Company) -> int:
    """
    Compute a quality score for *company*.

    Score breakdown (max = 7):
        website      → +2
        email        → +2
        contact_page → +1
        description  → +1
        address      → +1

    Returns:
        Integer in [0, MAX_SCORE].
    """
    return sum(
        weight
        for attr, weight in FIELD_WEIGHTS.items()
        if getattr(company, attr, None)
    )


def score_all(companies: list[Company]) -> list[Company]:
    """
    Assign a quality score to every company (mutates ``score`` in-place).

    Args:
        companies: List of Company objects to score.

    Returns:
        Same list with updated ``score`` fields.
    """
    for c in companies:
        c.score = score_company(c)
    return companies


def apply_min_score(companies: list[Company], min_score: int) -> list[Company]:
    """
    Keep only companies whose score is >= *min_score*.

    Args:
        companies: Scored company list.
        min_score: Inclusive minimum score threshold. 0 = keep all.

    Returns:
        Filtered (and already sorted) list.
    """
    if min_score <= 0:
        return companies
    kept = [c for c in companies if c.score >= min_score]
    dropped = len(companies) - len(kept)
    if dropped:
        logger.info(
            f"Score filter (min={min_score}/{MAX_SCORE}): "
            f"{len(kept)} kept, {dropped} dropped"
        )
    return kept
