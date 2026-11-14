"""Import an operator-supplied, authorized establishment catalog."""

import asyncio
import json
import re
from pathlib import Path

from models.company import Company
from scrapers.base import BaseSource, SourceError
from utils.deduplicator import normalize_text


class CatalogSource(BaseSource):
    name = "catalog"

    def __init__(self, path: Path) -> None:
        self.path = path

    async def search(self, query: str, location: str, limit: int) -> list[Company]:
        return await asyncio.to_thread(self._read, query, location, limit)

    def _read(self, query: str, location: str, limit: int) -> list[Company]:
        try:
            with self.path.open("rb") as source:
                payload = source.read(5_000_001)
            if len(payload) > 5_000_000:
                raise SourceError("catalog_too_large")
            rows = json.loads(payload)
        except (OSError, ValueError) as exc:
            raise SourceError("invalid_catalog") from exc
        if not isinstance(rows, list):
            raise SourceError("invalid_catalog")

        results = []
        for item in rows:
            if not isinstance(item, dict):
                raise SourceError("invalid_catalog_row")
            fields = {key: item.get(key) for key in (
                "company_name", "address", "website", "siret", "activity_code",
                "postal_code", "location", "activity",
            )}
            if any(value is not None and (not isinstance(value, str) or len(value) > 4096
                                          or any(ord(ch) < 32 or ord(ch) == 127 for ch in value))
                   for value in fields.values()):
                raise SourceError("invalid_catalog_field")
            if not fields["company_name"] or (siret := fields["siret"]) and not re.fullmatch("[0-9]{14}", siret):
                raise SourceError("invalid_catalog_identity")
            if (normalize_text(location) not in {
                normalize_text(fields.pop("location") or ""), fields["postal_code"],
            } or normalize_text(query) not in {
                normalize_text(fields.pop("activity") or ""), normalize_text(fields["activity_code"] or ""),
            }):
                continue
            fields["siren"] = siret[:9] if siret else None
            results.append(Company(**fields))
            if len(results) == limit:
                break
        return results
