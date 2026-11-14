"""Compare request budgets and identity retention on deterministic fixtures.

Run with python benchmarks/compare.py from a checkout with revision 8c687f6.
The baseline modules are loaded directly from that Git tree.
"""

import argparse
import asyncio
import io
import json
import resource
import statistics
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
URL = "https://atelierdesquais.fr"
HOME = '<title>Atelier</title><a href="/notre-salon/nous-ecrire">Contact</a>'
CONTACT = '<title>Contact</title><a href="mailto:bonjour@atelierdesquais.fr">Email</a>'


class FakeResponse:
    content_type = "text/html"
    content_length = None
    charset = None

    def __init__(self, url, latency):
        self.latency = latency
        body = {
            URL: HOME,
            URL + "/notre-salon/nous-ecrire": CONTACT,
            URL + "/robots.txt": "User-agent: *\nDisallow:",
        }.get(url)
        self.status = 200 if body else 404
        self.body = body or ""
        self.headers = {"Content-Type": "text/html"}
        self.content = self

    async def text(self, **kwargs):
        return self.body

    async def iter_chunked(self, size):
        yield self.body.encode()

    async def _response(self):
        await asyncio.sleep(self.latency)
        return self

    def __await__(self):
        return self._response().__await__()

    async def __aenter__(self):
        return await self

    async def __aexit__(self, *args):
        pass


class FakeHTTP:
    def __init__(self, latency):
        self.latency = latency
        self.requests = 0

    def get(self, url, **kwargs):
        self.requests += 1
        return FakeResponse(str(url), self.latency)


def run_variant(args):
    from config.settings import Settings
    from models.company import Company
    from scrapers.website_scraper import WebsiteScraper
    from utils.deduplicator import deduplicate

    settings = Settings()
    if args.variant == "before":
        settings.website_min_delay = settings.website_max_delay = 0
    scraper = WebsiteScraper(settings)
    rows = []
    for idx in range(1, 51):
        for _ in range(2):
            rows.append(Company("Atelier des Quais", website=URL, address=f"{idx} rue des Quais 33000 Bordeaux"))

    async def batch():
        client = FakeHTTP(args.latency_ms / 1000)
        semaphore = asyncio.Semaphore(5)
        times = []

        async def visit():
            async with semaphore:
                started = perf_counter()
                result = await scraper.scrape(URL, client)
                times.append(perf_counter() - started)
                if args.variant == "before":
                    return bool(result["contact_html"]), not bool(result["homepage_html"])
                return bool(result.linked_pages), result.homepage is None

        started = perf_counter()
        outcomes = await asyncio.gather(*(visit() for _ in range(args.sites)))
        return {
            "seconds": perf_counter() - started,
            "mean_enrichment_seconds": statistics.mean(times),
            "http_requests": client.requests,
            "contact_pages_found": sum(ok for ok, _ in outcomes),
            "enrichment_error_rate": sum(failed for _, failed in outcomes) / args.sites,
        }

    starts = perf_counter()
    matched = deduplicate(rows)
    dedup_time = perf_counter() - starts
    batches = [asyncio.run(batch()) for _ in range(args.repeats)]
    report = {key: statistics.median(batch[key] for batch in batches) for key in batches[0]}
    report.update({
        "sites_per_minute": round(60 * args.sites / report["seconds"], 2),
        "deduplication_seconds": dedup_time,
        "peak_process_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "annotated_establishments": 50,
        "establishments_retained": len({c.address for c in matched}),
        "duplicate_rows_remaining": len(matched) - len({c.address for c in matched}),
        "external_api_cost": 0,
    })
    print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="8c687f6")
    parser.add_argument("--sites", type=int, default=40)
    parser.add_argument("--latency-ms", type=float, default=3)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--variant", choices=("before", "after"), help=argparse.SUPPRESS)
    parser.add_argument("--tree", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if min(args.sites, args.repeats) < 1 or args.latency_ms < 0:
        parser.error("sites and repeats must be positive and latency non-negative")
    if args.variant:
        sys.path.insert(0, str(args.tree))
        run_variant(args)
        return

    def measure(variant, tree):
        return json.loads(subprocess.check_output([
            sys.executable, __file__, "--variant", variant, "--tree", str(tree),
            "--sites", str(args.sites), "--latency-ms", str(args.latency_ms), "--repeats", str(args.repeats),
        ], text=True))

    with tempfile.TemporaryDirectory(prefix="leadminer-benchmark-") as directory:
        archive = subprocess.check_output([
            "git", "archive", args.baseline, "config", "models", "scrapers", "utils",
        ], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as snapshot:
            snapshot.extractall(directory, filter="data")
        print(json.dumps({
            "baseline": args.baseline, "sites": args.sites, "repeats": args.repeats,
            "mock_latency_ms": args.latency_ms,
            "before": measure("before", directory), "after": measure("after", ROOT),
        }, indent=2))


if __name__ == "__main__":
    main()
