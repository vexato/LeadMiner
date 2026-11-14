"""Application logs go to stderr, separate from CLI output."""

import logging


def setup_logger(name: str = "LeadMiner", level: int | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if level is not None:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                            force=True)
    return logger
