#!/usr/bin/env python3
"""
LeadMiner — Company discovery CLI tool
========================================

Searches Google Maps for companies matching a domain + location, then
enriches each result with contact email, description, and contact page URL
gathered from the company's website.

Quick start
-----------
    python main.py --query "agence web" --location "Bordeaux" --limit 20
    python main.py -q "agence web" -l "Paris" -n 50 --format csv
    python main.py -q "startup tech" -l "Lyon" --only email,contact
"""

import argparse
import asyncio
import logging
import sys
from art import tprint

from dotenv import load_dotenv

# Load .env before anything else so os.environ is populated for all modules
load_dotenv()

from config.settings import Settings
from core.orchestrator import Orchestrator
from scrapers.registry import AVAILABLE_SOURCES, parse_sources
from utils.filters import parse_only, VALID_FIELDS
from utils.logger import setup_logger

logger = setup_logger("LeadMiner")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="LeadMiner",
        description="Find companies on Google Maps and enrich with website data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("--query",       "-q", required=True,
                        help='Search term, e.g. "agence web"')
    parser.add_argument("--location",    "-l", required=True,
                        help='City or region, e.g. "Bordeaux"')
    parser.add_argument(
        "--source", "-s",
        default="maps",
        metavar="SOURCES",
        help=(
            f"Comma-separated sources to run. Available: {', '.join(AVAILABLE_SOURCES)}. "
            "Default: maps. Example: --source maps,pj,google"
        ),
    )
    parser.add_argument("--limit",       "-n", type=int, default=20,
                        help="Max companies per source (default: 20)")
    parser.add_argument("--format",      "-f",
                        choices=["json", "csv", "both"], default="both",
                        dest="output_format",
                        help="Output format (default: both)")
    parser.add_argument("--output-dir",  "-o", default="results",
                        help="Output directory (default: results/)")
    parser.add_argument(
        "--only", metavar="FIELDS", default=None,
        help=(
            "Keep only companies with ALL listed fields populated. "
            f"Comma-separated subset of: {', '.join(sorted(VALID_FIELDS))}. "
            "Examples: --only email   --only email,contact"
        ),
    )
    parser.add_argument("--scroll-count", type=int, default=6,
                        help="Google Maps scroll iterations (default: 6)")
    parser.add_argument("--concurrency", type=int, default=5,
                        help="Parallel website scrapers (default: 5)")
    parser.add_argument("--no-headless", action="store_true",
                        help="Show browser window (useful for debugging)")
    parser.add_argument("--min-score",   type=int, default=0,
                        help="Keep only companies with quality score >= N (max 7, default: 0)")
    parser.add_argument("--no-filter",   action="store_true",
                        help="Disable the junk/empty-record filter")
    parser.add_argument("--ai",          action="store_true",
                        help="Run a final Groq-powered relevance filter "
                             "(requires GROQ_API_KEY env var)")
    parser.add_argument("--verbose",     "-v", action="store_true",
                        help="Enable DEBUG logging")

    return parser.parse_args()


def build_settings(args: argparse.Namespace) -> Settings:
    if args.verbose:
        for name in ("LeadMiner", "scrapers", "core", "extractors", "output", "utils"):
            setup_logger(name, level=logging.DEBUG)

    return Settings(
        headless=not args.no_headless,
        output_dir=args.output_dir,
        output_format=args.output_format,
        scroll_count=args.scroll_count,
        max_concurrent_website_scrapers=args.concurrency,
        min_score=args.min_score,
        filter_junk=not args.no_filter,
        filter_empty=not args.no_filter,
    )


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> int:
    args = parse_args()
    settings = build_settings(args)

    tprint("LeadMiner")
    try:
        sources = parse_sources(args.source)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    only: list[str] | None = None
    if args.only:
        try:
            only = parse_only(args.only)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2

    companies = await Orchestrator(settings).run(
        query=args.query,
        location=args.location,
        limit=args.limit,
        sources=sources,
        only=only,
        ai=args.ai,
    )

    if not companies:
        print("\nNo results found.")
        return 1

    # ── Summary table ─────────────────────────────────────────────────────────
    from utils.scorer import MAX_SCORE
    print(f"\n{'─' * 64}")
    print(f"  Found {len(companies)} companies")
    print(f"{'─' * 64}")
    for i, c in enumerate(companies, 1):
        score_tag = f"[{c.score}/{MAX_SCORE}]"
        sources_tag = f"  ({', '.join(c.sources)})" if c.sources else ""
        print(f"\n{i:>3}. {c.company_name}  {score_tag}{sources_tag}")
        if c.website:
            print(f"     🌐  {c.website}")
        if c.email:
            print(f"     ✉   {c.email}")
        if c.address:
            print(f"     📍  {c.address}")
        if c.contact_page:
            print(f"     📋  {c.contact_page}")
        if c.description:
            snippet = c.description[:100].rstrip()
            print(f"     💬  {snippet}{'…' if len(c.description) > 100 else ''}")
    print(f"\n{'─' * 64}\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        logger.info("Interrupted.")
        sys.exit(130)
