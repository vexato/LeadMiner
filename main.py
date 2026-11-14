"""LeadMiner command line interface."""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv

from config.settings import Settings, database_url
from core.orchestrator import Orchestrator, Search, export_result
from output.exporter import Exporter
from scrapers.registry import AVAILABLE_SOURCES, DEFAULT_SOURCE, LEGACY_SOURCES, build_source, parse_sources
from utils.filters import parse_only
from utils.logger import setup_logger

logger = setup_logger("LeadMiner")


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Discover B2B establishments and export their evidence.")
    parser.add_argument("-q", "--query", help="Activity, NAF code or business name")
    parser.add_argument("-l", "--location", help="French commune or postal code")
    locations = ", ".join(AVAILABLE_SOURCES)
    parser.add_argument("-s", "--source", default=DEFAULT_SOURCE, help=f"Comma-separated sources ({locations})")
    parser.add_argument("-n", "--limit", type=int, default=20, help="Maximum records per source (default: 20)")
    parser.add_argument("-f", "--format", choices=("json", "csv", "both"), default="both")
    parser.add_argument("-o", "--output-dir", default=os.getenv("LEADMINER_OUTPUT_DIR", "results"))
    parser.add_argument("--only", help="Required fields, e.g. email,contact")
    parser.add_argument("--scroll-count", type=int, default=6)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--min-score", type=int, default=0, help="Legacy completeness score (-2 to 11)")
    parser.add_argument("--no-filter", action="store_true")
    parser.add_argument("--ai", action="store_true", help="Use your Groq account to classify relevance")
    parser.add_argument("--catalog", type=Path, help="Authorized local JSON catalog")
    parser.add_argument("--radius-km", type=float, help="Radius from the commune centre, with Sirene and a NAF code")
    parser.add_argument("--allow-legacy-sources", action="store_true",
                        help="Enable authorized legacy browser sources using LEADMINER_LEGACY_PROXY")
    parser.add_argument("--resume", type=UUID, metavar="SEARCH_ID", help="Resume a persisted search")
    administration = parser.add_mutually_exclusive_group()
    administration.add_argument("--suppress", metavar="SIREN_OR_SIRET", help="Record an opposition and purge snapshots")
    administration.add_argument("--delete-search", type=UUID, metavar="SEARCH_ID")
    parser.add_argument("--metrics", type=Path, help="Write search metrics to a JSON file")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


async def run(args, repo) -> int:
    if args.suppress or args.delete_search:
        if not repo:
            raise ValueError("PostgreSQL is required")
        if args.suppress:
            await repo.suppress(args.suppress)
            print("Opposition recorded.")
            return 0
        return 0 if await repo.delete_search(args.delete_search) else 1

    settings = Settings(
        headless=not args.no_headless, output_dir=args.output_dir, output_format=args.format,
        scroll_count=args.scroll_count, max_concurrent_website_scrapers=args.concurrency,
        legacy_proxy=os.getenv("LEADMINER_LEGACY_PROXY") if args.allow_legacy_sources else None,
    )

    search_id = args.resume
    if search_id:
        if not repo:
            raise ValueError("--resume requires PostgreSQL")
        if args.query is not None or args.location is not None:
            raise ValueError("--resume uses the stored query and location")
        from storage.repository import search_from_params

        row = await repo.get(search_id)
        if row is None:
            raise ValueError("Unknown search ID")
        search = search_from_params(row.parameters)
    else:
        if args.query is None or args.location is None:
            raise ValueError("--query and --location are required")
        search = Search(args.query, args.location, args.limit, tuple(parse_sources(args.source)),
                        tuple(parse_only(args.only)) if args.only else (), args.min_score,
                        not args.no_filter, args.radius_km)

    if set(search.sources) & set(LEGACY_SOURCES) and not settings.legacy_proxy:
        raise ValueError("Legacy sources require --allow-legacy-sources and LEADMINER_LEGACY_PROXY")
    if "catalog" in search.sources and args.catalog is None:
        if search_id is None or not await repo.has_discovery(search_id, "catalog"):
            raise ValueError("The catalog source requires --catalog until discovery is checkpointed")
    engine = Orchestrator(settings, source_factory=lambda name, spec: build_source(
        name, settings, catalog=args.catalog, radius_km=spec.radius_km,
    ))
    if not repo:
        result = await engine.execute(search, ai=args.ai)
    else:
        if search_id is None:
            search_id = await repo.create(search)
        print(f"Search ID {search_id}", flush=True)
        result = await repo.run(search_id, engine, ai=args.ai)
        if result is None:
            print("Search is already running.", file=sys.stderr)
            return 2

    for path in export_result(Exporter(settings), search, result, str(search_id) if search_id else None):
        print(f"Saved {path}")
    if args.metrics:
        args.metrics.write_text(json.dumps(result.metrics, indent=2) + "\n", encoding="utf-8")
    print(f"{len(result.companies)} establishments ({result.status})")
    if result.status in {"partial", "failed"}:
        return 2
    return 0 if result.companies else 1


async def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    setup_logger("LeadMiner", logging.DEBUG if args.verbose else logging.INFO)
    repo = None
    try:
        url = database_url()
        if url:
            from storage.repository import Repository

            repo = Repository(url)
        return await run(args, repo)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    finally:
        if repo:
            await repo.close()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        logger.info("Interrupted")
        sys.exit(130)
