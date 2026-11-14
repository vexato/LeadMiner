"""Poll PostgreSQL and run searches outside HTTP request lifetimes."""

import argparse
import asyncio
import logging
import signal

from config.settings import database_url
from core.orchestrator import Orchestrator
from storage.repository import Repository
from utils.logger import setup_logger

logger = setup_logger(__name__)


async def worker(once: bool) -> None:
    url = database_url()
    if not url:
        raise RuntimeError("PostgreSQL is required")
    repository = Repository(url)
    engine = Orchestrator()
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    if task is not None:
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        while True:
            for identifier in await repository.pending():
                try:
                    await repository.run(identifier, engine, public_worker=True)
                except LookupError:
                    continue
                except Exception as exc:
                    logger.error("Search %s execution error (%s)", identifier, type(exc).__name__)
            if once:
                return
            await asyncio.sleep(2)
    finally:
        loop.remove_signal_handler(signal.SIGTERM)
        await repository.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    setup_logger(__name__, logging.INFO)
    try:
        asyncio.run(worker(parser.parse_args().once))
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Worker stopped")
