"""Search engine independent of files, CLI and HTTP."""

import asyncio
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from math import isfinite
from time import perf_counter

from config.settings import Settings
from core.pipeline import Pipeline
from core.qualification import WebAgencyProfile
from models.company import Company
from scrapers.base import BaseSource, SourceError
from scrapers.registry import DEFAULT_SOURCE, LEGACY_SOURCES, build_source
from utils.deduplicator import deduplicate
from utils.filter import apply_junk_filter
from utils.filters import VALID_FIELDS, apply_only
from utils.logger import setup_logger
from utils.scorer import MAX_SCORE, apply_min_score, score_company

logger = setup_logger(__name__)


@dataclass(frozen=True)
class Search:
    query: str
    location: str
    limit: int = 20
    sources: tuple[str, ...] = (DEFAULT_SOURCE,)
    only: tuple[str, ...] = ()
    min_score: int = 0
    filter_junk: bool = True
    radius_km: float | None = None

    def __post_init__(self):
        for field_name in ("query", "location"):
            value = getattr(self, field_name).strip()
            if not 1 <= len(value) <= 120 or not value.isprintable():
                raise ValueError(f"Invalid {field_name}: expected 1 to 120 printable characters")
            object.__setattr__(self, field_name, value)
        if not 1 <= self.limit <= 200:
            raise ValueError("Limit must be between 1 and 200 per source")
        if not self.sources or len(set(self.sources)) != len(self.sources):
            raise ValueError("Select distinct discovery sources")
        if set(self.only) - VALID_FIELDS or not -2 <= self.min_score <= MAX_SCORE:
            raise ValueError("Invalid required fields or minimum score")
        if self.radius_km is not None and (
            not isfinite(self.radius_km) or not 0 < self.radius_km <= 50
            or self.sources != (DEFAULT_SOURCE,)
        ):
            raise ValueError("Radius must be between 0 and 50 km and requires the sirene source")


@dataclass
class Discovery:
    companies: list[Company] = field(default_factory=list)
    error: str | None = None
    seconds: float = 0
    opposed_sirens: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**{**data, "companies": [Company.from_dict(row) for row in data["companies"]]})


@dataclass
class SearchResult:
    companies: list[Company]
    metrics: dict
    status: str
    refused: list[Company] = field(default_factory=list)


class Orchestrator:
    def __init__(self, settings: Settings | None = None, *, source_factory=None) -> None:
        self.settings = settings or Settings()
        self.source_factory = source_factory or (lambda name, search: build_source(
            name, self.settings, radius_km=search.radius_km,
        ))
        self.pipeline = Pipeline(self.settings)
        self.profile = WebAgencyProfile()

    async def execute(self, search: Search, *, journal=None, ai: bool = False) -> SearchResult:
        started = perf_counter()
        source_limit = asyncio.Semaphore(self.settings.max_concurrent_sources)
        browser_limit = asyncio.Semaphore(1)

        async def discover(name: str) -> Discovery:
            if journal:
                prior = await journal.get_discovery(name)
                if prior is not None:
                    return prior
            source = self.source_factory(name, search)
            async with source_limit:
                if name in LEGACY_SOURCES:
                    async with browser_limit:
                        batch = await self._discover(source, search)
                else:
                    batch = await self._discover(source, search)
            if journal:
                await journal.save_discovery(name, batch)
            logger.info("Discovery %s: %d records in %.2fs (%s)", name, len(batch.companies),
                        batch.seconds, batch.error or "completed")
            return batch

        source_started = perf_counter()
        tasks = []
        async with asyncio.TaskGroup() as group:
            for name in search.sources:
                tasks.append(group.create_task(discover(name)))
        batches = [task.result() for task in tasks]
        source_seconds = perf_counter() - source_started

        all_rows = [row for batch in batches for row in batch.companies]
        blocked = {siren for batch in batches for siren in batch.opposed_sirens}
        raw = [row for row in all_rows if row.siren not in blocked and row.is_valid()]
        association_started = perf_counter()
        candidates = deduplicate(raw)
        association_seconds = perf_counter() - association_started
        merged_count = len(raw) - len(candidates)

        if journal:
            candidates, finished = await journal.prepare(candidates)
        else:
            finished = set()

        enrichment_seconds = []

        async def checkpoint(idx, company):
            company.score = score_company(company)
            company.qualification = self.profile.evaluate(company)
            if journal:
                await journal.save_result(idx, company)

        enrich_started = perf_counter()
        await self.pipeline.enrich_all(candidates, finished=finished, checkpoint=checkpoint,
                                       timings=enrichment_seconds)
        enrich_seconds = perf_counter() - enrich_started

        if journal:
            candidates = await journal.visible_candidates(candidates)
        valid = candidates
        if search.filter_junk:
            valid = apply_junk_filter(valid, filter_empty=self.settings.filter_empty)
        valid = apply_only(valid, list(search.only))
        valid = apply_min_score(valid, search.min_score)
        valid = sorted(valid, key=lambda row: row.score, reverse=True)

        refused = []
        if ai:
            from utils.ai_filter import AIFilterError, ai_filter

            try:
                valid, refused = await ai_filter(valid, search.query)
            except AIFilterError as exc:
                logger.error("AI classification unavailable (%s)", exc)

        errors = sum(batch.error is not None for batch in batches)
        status = "failed" if errors == len(batches) and not raw else "partial" if errors else "completed"
        metrics = {
            "total_seconds": round(perf_counter() - started, 6),
            "source_wall_seconds": round(source_seconds, 6),
            "deduplication_seconds": round(association_seconds, 6),
            "enrichment_seconds": round(enrich_seconds, 6),
            "mean_enrichment_seconds": round(sum(enrichment_seconds) / len(enrichment_seconds), 6)
            if enrichment_seconds else None,
            "sources": {
                name: {"seconds": batch.seconds, "count": len(batch.companies), "error": batch.error}
                for name, batch in zip(search.sources, batches, strict=True)
            },
            "discovered": len(raw),
            "deduplicated": len(candidates),
            "returned": len(valid),
            "records_per_minute": round(len(raw) * 60 / source_seconds, 2) if source_seconds else 0,
            "enrichment_failures": sum(c.enrichment_status in {"failed", "partial", "invalid_url"}
                                       for c in candidates),
            "duplicates_removed": merged_count,
            "usable_records": sum(bool(c.siret or (c.address and c.website_status == "official_confirmed"))
                                  for c in valid),
        }
        if journal:
            await journal.complete(status, valid, refused, metrics)
        logger.info("Search %s with %d results (%.2fs)", status, len(valid), metrics["total_seconds"])
        return SearchResult(valid, metrics, status, refused)

    async def _discover(self, source: BaseSource, search: Search) -> Discovery:
        started = perf_counter()
        error = None
        try:
            async with asyncio.timeout(self.settings.source_timeout):
                companies = await source.search(search.query, search.location, search.limit)
        except SourceError as exc:
            error, companies = str(exc), exc.partial
        except TimeoutError:
            error, companies = "source_timeout", []
        except Exception as exc:
            error, companies = f"source_error_{type(exc).__name__}", []
        for company in companies:
            company.record_discovery(source.name)
            if company.siret and re.fullmatch(r"[0-9]{14}", company.siret):
                if company.siren and company.siren != company.siret[:9]:
                    company.identity_notes.append("siren_siret_conflict")
                    company.siret = company.siren = None
                elif not company.siren:
                    company.siren = company.siret[:9]
                    company.observe("siren", company.siren, source.name, "siret_prefix")
            elif company.siret:
                company.identity_notes.append("invalid_siret")
                company.siret = None
        return Discovery(companies, error, round(perf_counter() - started, 6),
                         sorted(getattr(source, "opposed_sirens", ())))

    async def run(self, query: str, location: str, limit: int, sources: list[str] | None = None,
                  output_format: str | None = None, only: list[str] | None = None,
                  ai: bool = False) -> list[Company]:
        """Compatibility entry point that also writes the historical file outputs."""
        from dataclasses import replace

        from output.exporter import Exporter

        search = Search(query, location, limit, tuple(sources or [DEFAULT_SOURCE]), tuple(only or ()),
                        self.settings.min_score, self.settings.filter_junk)
        result = await self.execute(search, ai=ai)
        settings = replace(self.settings, output_format=output_format or self.settings.output_format)
        export_result(Exporter(settings), search, result)
        return result.companies


def export_result(exporter, search: Search, result: SearchResult, run_id: str | None = None) -> list[str]:
    uid = run_id or datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    stem = f"{'_'.join(search.sources)[:22]}_{search.query[:22]}_{search.location[:22]}_{uid}"
    paths = exporter.export(result.companies, search.query, search.location, stem)
    paths.extend(exporter.export(result.refused, search.query, search.location, stem + "_refused"))
    return paths
