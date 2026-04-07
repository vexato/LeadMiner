"""
AI relevance filter using the Groq API.

Runs as the final pipeline stage when the user passes ``--ai`` on the CLI.
For each company, it asks a small Llama model whether the company truly
matches the original search query, and splits the list into *kept* and
*refused* buckets.
"""

import os
import time
from typing import Tuple

from models.company import Company
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Groq free-tier rate limit for llama-3.1-8b-instant is 30 req/min.
# We pause for a full minute after every batch of this size.
_REQUESTS_PER_MINUTE = 30
_COOLDOWN_SECONDS = 61


class AIFilterError(RuntimeError):
    """Raised when the AI filter cannot run (missing dep, missing API key, …)."""


def _build_client():
    """Create a Groq client or raise AIFilterError with a helpful message."""
    try:
        from groq import Groq  # type: ignore
    except ImportError as exc:
        raise AIFilterError(
            "The 'groq' package is not installed. Run `pip install groq`."
        ) from exc

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise AIFilterError(
            "GROQ_API_KEY environment variable is not set. "
            "Export it before running with --ai."
        )

    return Groq(api_key=api_key)


def _ask_groq(client, query: str, company: Company) -> bool:
    """
    Ask the model whether *company* matches *query*.

    Returns:
        True  if the model answers 'oui'
        False if the model answers 'non' (or anything else)
    """
    response = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": (
                    "Tu es un filtre de pertinence. Tu réponds UNIQUEMENT "
                    "par 'oui' ou 'non', rien d'autre."
                ),
            },
            {
                "role": "user",
                "content": (
                    f'Cette entreprise correspond-elle à la recherche "{query}" ?\n\n'
                    f"Nom : {company.company_name}\n"
                    f"Description : {company.description or ''}\n\n"
                    "Réponds uniquement 'oui' ou 'non'."
                ),
            },
        ],
        model="llama-3.1-8b-instant",
        max_tokens=5,
        temperature=0,
    )

    raw = (response.choices[0].message.content or "").strip().lower()
    # Be lenient: accept 'oui', 'oui.', 'yes' etc. but anything else → refused
    return raw.startswith("oui")


def ai_filter(
    companies: list[Company],
    query: str,
) -> Tuple[list[Company], list[Company]]:
    """
    Split *companies* into (kept, refused) by asking Groq about each one.

    Args:
        companies: Companies to evaluate (post-scoring, post-dedup).
        query:     Original search query the pipeline was started with.

    Returns:
        (kept, refused) — two disjoint lists whose union is *companies*.

    Raises:
        AIFilterError: if the Groq SDK or GROQ_API_KEY env var is missing.
    """
    if not companies:
        return [], []

    client = _build_client()

    kept: list[Company] = []
    refused: list[Company] = []

    for idx, company in enumerate(companies):
        # Rate-limit: pause 60s after every batch of 30 requests
        if idx > 0 and idx % _REQUESTS_PER_MINUTE == 0:
            print(
                f"[IA] Limite atteinte ({_REQUESTS_PER_MINUTE} req/min) — "
                f"pause de {_COOLDOWN_SECONDS}s…"
            )
            time.sleep(_COOLDOWN_SECONDS)

        try:
            is_relevant = _ask_groq(client, query, company)
        except Exception as exc:  # network / rate limit / etc.
            logger.warning(
                f"[IA] API error on '{company.company_name}': {exc} — "
                "keeping company by default"
            )
            is_relevant = True

        verdict = "oui" if is_relevant else "non"
        print(f"[IA] Filtrage {company.company_name}... → {verdict}")

        if is_relevant:
            kept.append(company)
        else:
            refused.append(company)

    print(
        f"[IA] {len(companies)} entreprises → "
        f"{len(kept)} gardées, {len(refused)} refusées"
    )
    return kept, refused
