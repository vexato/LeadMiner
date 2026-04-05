"""Export enriched companies to JSON and/or CSV."""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.settings import Settings
from models.company import Company
from utils.logger import setup_logger

logger = setup_logger(__name__)


class Exporter:
    """
    Writes company data to disk in one or both of: JSON, CSV.

    Files are named ``{query}_{location}_{timestamp}.{ext}`` and placed
    in ``settings.output_dir`` (created automatically if absent).
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._out = Path(settings.output_dir)
        self._out.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        companies: list[Company],
        query: str,
        location: str,
    ) -> list[str]:
        """
        Write *companies* to configured format(s) and return the file paths.

        Args:
            companies: Enriched Company objects to export.
            query:     Used to build the output filename.
            location:  Used to build the output filename.

        Returns:
            List of absolute paths to files written.
        """
        if not companies:
            logger.warning("No companies to export.")
            return []

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = f"{query}_{location}".lower().replace(" ", "_")
        base = f"{slug}_{ts}"
        fmt = self.settings.output_format.lower()

        paths: list[str] = []

        if fmt in ("json", "both"):
            paths.append(self._write_json(companies, base))

        if fmt in ("csv", "both"):
            paths.append(self._write_csv(companies, base))

        return paths

    # ── Formats ───────────────────────────────────────────────────────────────

    def _write_json(self, companies: list[Company], base: str) -> str:
        path = self._out / f"{base}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([c.to_clean_dict() for c in companies], fh, ensure_ascii=False, indent=2)
        logger.debug(f"JSON → {path} ({len(companies)} records)")
        return str(path)

    def _write_csv(self, companies: list[Company], base: str) -> str:
        path = self._out / f"{base}.csv"
        df = pd.DataFrame([c.to_dict() for c in companies])
        # utf-8-sig BOM makes the file open correctly in Excel
        df.to_csv(path, index=False, encoding="utf-8-sig")
        logger.debug(f"CSV  → {path} ({len(df)} records)")
        return str(path)
