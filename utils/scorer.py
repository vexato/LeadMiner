"""
Quality scoring for Company objects.

Each company receives a numeric score based on which fields are populated
and how trustworthy those fields are. The goal is a **wide** spread so
downstream sorting surfaces the best leads — not a flat list of ties.

Score breakdown (range: -2 .. 11)
    website              → +2
    email (professional) → +3     (domain not a free provider)
    email (free / gmail) → -2     (replaces the +3 — keeps bad leads scorable but last)
    address              → +2
    multiple sources     → +2     (len(sources) >= 2)
    contact_page         → +1
    description          → +1
"""

from models.company import Company
from utils.logger import setup_logger
from utils.validators import is_free_email_provider

logger = setup_logger(__name__)


# Simple flat-field weights (presence → points)
_FLAT_WEIGHTS: dict[str, int] = {
    "website":      2,
    "address":      2,
    "contact_page": 1,
    "description":  1,
}

EMAIL_PRO_BONUS = 3
EMAIL_FREE_PENALTY = -2
MULTI_SOURCE_BONUS = 2

# Max = website(2) + address(2) + contact(1) + desc(1) + pro_email(3) + multi_source(2)
MAX_SCORE: int = (
    sum(_FLAT_WEIGHTS.values()) + EMAIL_PRO_BONUS + MULTI_SOURCE_BONUS
)  # 11

# Min = only a free-provider email present (every other field empty, single source)
MIN_SCORE: int = EMAIL_FREE_PENALTY  # -2


def score_company(company: Company) -> int:
    """
    Compute a quality score for *company* in the range [MIN_SCORE, MAX_SCORE].
    """
    score = 0

    for attr, weight in _FLAT_WEIGHTS.items():
        if getattr(company, attr, None):
            score += weight

    # Email: reward professional addresses, penalise free providers
    email = getattr(company, "email", None)
    if email:
        if is_free_email_provider(email):
            score += EMAIL_FREE_PENALTY
        else:
            score += EMAIL_PRO_BONUS

    # Multi-source confidence bump
    sources = getattr(company, "sources", None) or []
    if len(sources) >= 2:
        score += MULTI_SOURCE_BONUS

    return score


def score_all(companies: list[Company]) -> list[Company]:
    """Assign a quality score to every company (mutates ``score`` in place)."""
    for c in companies:
        c.score = score_company(c)
    return companies


def apply_min_score(companies: list[Company], min_score: int) -> list[Company]:
    """
    Keep only companies whose score is >= *min_score*.

    A threshold of 0 (default) keeps everything except pure free-email leads
    with no other fields populated. Pass a negative number to disable.
    """
    if min_score <= MIN_SCORE:
        return companies
    kept = [c for c in companies if c.score >= min_score]
    dropped = len(companies) - len(kept)
    if dropped:
        logger.info(
            f"Score filter (min={min_score}/{MAX_SCORE}): "
            f"{len(kept)} kept, {dropped} dropped"
        )
    return kept
