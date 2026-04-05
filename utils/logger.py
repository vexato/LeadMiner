"""Logging setup for the internship tool."""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str = "internship",
    level: int = logging.INFO,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """
    Build and return a named logger.

    Args:
        name:     Logger name (use __name__ in modules).
        level:    Logging level for the console handler.
        log_file: Optional path for a DEBUG-level file handler.

    Returns:
        Configured Logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # capture everything; handlers filter

    if logger.handlers:
        return logger  # already configured — avoid duplicate handlers

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # Console
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # File (optional)
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger
