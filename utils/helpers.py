"""Shared utilities: retry decorators, rate-limiting delays, URL helpers."""

import asyncio
import functools
import random
import time
from typing import Any, Callable, TypeVar

from utils.logger import setup_logger

logger = setup_logger(__name__)
T = TypeVar("T")


# ── Delays ────────────────────────────────────────────────────────────────────

def random_delay(min_s: float = 1.0, max_s: float = 3.0) -> None:
    """Synchronous random sleep for rate limiting."""
    time.sleep(random.uniform(min_s, max_s))


async def async_random_delay(min_s: float = 0.5, max_s: float = 1.5) -> None:
    """Asynchronous random sleep for rate limiting."""
    await asyncio.sleep(random.uniform(min_s, max_s))


# ── Retry decorators ──────────────────────────────────────────────────────────

def retry(
    max_attempts: int = 3,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """Decorator: sync retry with exponential back-off."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == max_attempts:
                        logger.error(f"[{func.__name__}] Giving up after {max_attempts} attempts: {exc}")
                        raise
                    wait = backoff ** attempt
                    logger.warning(f"[{func.__name__}] Attempt {attempt} failed ({exc}). Retrying in {wait:.1f}s…")
                    time.sleep(wait)

        return wrapper

    return decorator


def async_retry(
    max_attempts: int = 3,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """Decorator: async retry with exponential back-off."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == max_attempts:
                        logger.error(f"[{func.__name__}] Giving up after {max_attempts} attempts: {exc}")
                        raise
                    wait = backoff ** attempt
                    logger.warning(f"[{func.__name__}] Attempt {attempt} failed ({exc}). Retrying in {wait:.1f}s…")
                    await asyncio.sleep(wait)

        return wrapper

    return decorator


# ── URL helpers ───────────────────────────────────────────────────────────────

def normalize_url(url: str) -> str:
    """Ensure a URL has a scheme; default to https."""
    url = url.strip()
    if url and not url.startswith(("http://", "https://")):
        return f"https://{url}"
    return url
