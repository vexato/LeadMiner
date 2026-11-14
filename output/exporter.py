"""Atomic JSON and CSV exports with safe file names and cells."""

import csv
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from config.settings import Settings
from models.company import Company


class Exporter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._out = Path(settings.output_dir)

    def export(self, companies: list[Company], query: str, location: str,
               base_name: str | None = None) -> list[str]:
        if not companies:
            return []
        if not base_name:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            base_name = f"{query[:45]}_{location[:45]}_{timestamp}"
        base = re.sub(r"[^\w-]+", "_", base_name.lower()).strip("_")[:120] or "leadminer"
        self._out.mkdir(parents=True, exist_ok=True)

        outputs = []
        formats = ("json", "csv") if self.settings.output_format == "both" else (self.settings.output_format,)
        for fmt in formats:
            path = self._out / f"{base}.{fmt}"
            with tempfile.NamedTemporaryFile(
                dir=self._out, mode="w", encoding="utf-8-sig" if fmt == "csv" else "utf-8",
                newline="", delete=False,
            ) as file:
                temp = Path(file.name)
                try:
                    if fmt == "json":
                        json.dump([c.to_clean_dict() for c in companies], file, ensure_ascii=False, indent=2, sort_keys=True)
                    else:
                        writer = csv.DictWriter(file, fieldnames=list(companies[0].to_dict()))
                        writer.writeheader()
                        for company in companies:
                            writer.writerow({key: _safe_cell(value) for key, value in company.to_dict().items()})
                    file.close()
                    os.replace(temp, path)
                finally:
                    temp.unlink(missing_ok=True)
            outputs.append(str(path.resolve()))
        return outputs


def _safe_cell(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, str) and (value.startswith(("\r", "\n", "\t"))
                                   or value.lstrip().startswith(("=", "+", "-", "@"))):
        return "'" + value
    return value
