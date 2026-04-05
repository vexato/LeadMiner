"""
Top-level orchestrator.

Pipeline
--------
  1. [Search]      Each active source runs the same query  →  list[Company]
  2. [Tag]         Stamp each result with its source name
  3. [Deduplicate] Merge records by name / domain          →  list[Company]
  4. [Enrich]      Visit each website                      →  list[Company]
  5. [Score]       Assign quality score to every record
  6. [Filter]      Junk domains, empty records, min-score  →  list[Company]
  7. [Sort]        Descending by score
  8. [Export]      JSON / CSV                              →  files
"""

from typing import Optional

from config.settings import Settings
from core.pipeline import Pipeline
from models.company import Company
from output.exporter import Exporter
from scrapers.registry import build_source
from utils.deduplicator import deduplicate
from utils.filter import apply_junk_filter
from utils.filters import apply_only
from utils.logger import setup_logger
from utils.scorer import apply_min_score, score_all

logger = setup_logger(__name__)


class Orchestrator:
    """
    Wires all components together and runs the pipeline end-to-end.

    Usage::

        await Orchestrator(settings).run(
            query="agence web",
            location="Bordeaux",
            limit=20,
            sources=["maps", "pj", "google"],
        )
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or Settings()
        self.pipeline = Pipeline(self.settings)
        self.exporter = Exporter(self.settings)

    async def run(
        self,
        query: str,
        location: str,
        limit: int,
        sources: Optional[list[str]] = None,
        output_format: Optional[str] = None,
        only: Optional[list[str]] = None,
    ) -> list[Company]:
        """
        Execute the full pipeline.

        Args:
            query:         Search term (e.g. "agence web").
            location:      Target city/region (e.g. "Bordeaux").
            limit:         Max companies *per source*.
            sources:       Source names to run (default: ["maps"]).
                           Available: maps, pj, google.
            output_format: Override settings output format.
            only:          Required-field filter (e.g. ["email", "contact"]).
        """
        if output_format:
            self.settings.output_format = output_format

        active = sources or ["maps"]
        logger.info(
            f"Pipeline start — query='{query}' location='{location}' "
            f"limit={limit} sources={active}"
            + (f" only=[{', '.join(only)}]" if only else "")
        )

        # ── Step 1: discover ──────────────────────────────────────────────────
        logger.info(f"[1/7] Running {len(active)} source(s)…")
        all_companies: list[Company] = []

        for source_name in active:
            scraper = build_source(source_name, self.settings)
            results = await scraper.search(query, location, limit)
            # Tag each result with its origin source
            for c in results:
                if source_name not in c.sources:
                    c.sources.append(source_name)
            logger.info(f"  [{scraper.name}] → {len(results)} companies")
            all_companies.extend(results)

        if not all_companies:
            logger.warning("No companies discovered — pipeline aborted.")
            return []

        # ── Step 2: deduplicate + merge ───────────────────────────────────────
        before = len(all_companies)
        all_companies = deduplicate(all_companies)
        logger.info(
            f"[2/7] Deduplicated: {before} → {len(all_companies)} unique companies"
        )

        # ── Step 3: enrich ────────────────────────────────────────────────────
        logger.info("[3/7] Enriching companies via their websites…")
        enriched = await self.pipeline.enrich_all(all_companies)
        valid = [c for c in enriched if c.is_valid()]
        logger.info(f"[3/7] {len(valid)} valid companies after enrichment")

        # ── Step 4: score ─────────────────────────────────────────────────────
        score_all(valid)
        logger.info("[4/7] Quality scores assigned")

        # ── Step 5: junk filter ───────────────────────────────────────────────
        if self.settings.filter_junk:
            valid = apply_junk_filter(
                valid, filter_empty=self.settings.filter_empty
            )
        logger.info(f"[5/7] {len(valid)} companies after junk filter")

        # ── Step 6: --only field filter ───────────────────────────────────────
        if only:
            valid = apply_only(valid, only)

        # ── Step 7: min-score filter + sort ───────────────────────────────────
        valid = apply_min_score(valid, self.settings.min_score)
        valid.sort(key=lambda c: c.score, reverse=True)
        logger.info(f"[6/7] {len(valid)} companies after score filter, sorted by score")

        # ── Step 8: export ────────────────────────────────────────────────────
        source_label = "_".join(active)
        logger.info(f"[7/7] Exporting {len(valid)} companies…")
        for path in self.exporter.export(valid, f"{source_label}_{query}", location):
            logger.info(f"  Saved → {path}")

        logger.info("Pipeline complete.")
        return valid
