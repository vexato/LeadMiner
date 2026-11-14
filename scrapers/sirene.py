"""Discover active, publicly diffusible establishments via the DINUM API."""

import asyncio
import json
import random
import re
from math import asin, cos, radians, sin, sqrt

import aiohttp

from config.settings import Settings
from models.company import Company
from scrapers.base import BaseSource, SourceError
from utils.deduplicator import normalize_text
from utils.public_http import FetchError, bounded_body, public_session, public_url

_API = "https://recherche-entreprises.api.gouv.fr"
_GEO = "https://geo.api.gouv.fr/communes"
_NAF = re.compile(r"\d{2}\.\d{2}[A-Z]")
_ACTIVITY_ALIASES = {
    "coiffeur": "96.02A", "coiffeurs": "96.02A", "coiffure": "96.02A",
    "salon de coiffure": "96.02A", "salons de coiffure": "96.02A",
    "boulangerie": "10.71C", "boulangeries": "10.71C",
}
_REQUEST_INTERVAL = 0.25
_SUPPRESSION_SIREN = re.compile(r"[0-9]{9}")


class SireneSource(BaseSource):
    name = "sirene"

    def __init__(self, settings: Settings, radius_km: float | None = None) -> None:
        self.settings = settings
        self.radius_km = radius_km
        self.opposed_sirens: set[str] = set()

    async def search(self, query: str, location: str, limit: int) -> list[Company]:
        self.opposed_sirens.clear()
        async with public_session(10) as session:
            return await self._search(session, query, location, limit)

    async def _search(self, session, query: str, location: str, limit: int) -> list[Company]:
        naf = query.upper() if _NAF.fullmatch(query.upper()) else _ACTIVITY_ALIASES.get(normalize_text(query))
        if self.radius_km is not None and not naf:
            raise SourceError("radius_requires_naf_code")
        if re.fullmatch(r"[0-9]{9}|[0-9]{14}", query):
            raise SourceError("use_an_activity_code_or_a_text_query")

        postal = re.fullmatch(r"[0-9]{5}", location) is not None
        criteria = {"code_postal": location} if postal else {"nom": location}
        communes, _ = await self._json(session, _GEO, {
            **criteria, "limit": "25", "fields": "code,nom,centre,codesPostaux",
        })
        if not isinstance(communes, list):
            raise SourceError("invalid_communes_response")
        exact = [
            item for item in communes if isinstance(item, dict) and (
                location in (item.get("codesPostaux") or []) if postal
                else normalize_text(item.get("nom", "")) == normalize_text(location)
            )
        ]
        if len(exact) != 1 and (not postal or self.radius_km is not None):
            raise SourceError("commune_unknown_or_ambiguous_use_postal_code")

        endpoint = "/search"
        center = None
        if self.radius_km is not None:
            endpoint = "/near_point"
            coords = (exact[0].get("centre") or {}).get("coordinates")
            if not coords or len(coords) != 2:
                raise SourceError("commune_coordinates_unavailable")
            center = coords
            geographic = {"long": str(coords[0]), "lat": str(coords[1]), "radius": str(self.radius_km)}
        else:
            geographic = {"code_postal": location} if postal else {"code_commune": exact[0]["code"]}

        params = {
            **geographic, "minimal": "true", "include": "matching_etablissements",
            "per_page": "25", "limite_matching_etablissements": "100",
            **({"activite_principale": naf} if naf else {"q": query}),
        }
        companies: dict[str, Company] = {}
        for page in range(1, 21):
            if page > 1:
                await asyncio.sleep(_REQUEST_INTERVAL)
            try:
                data, url = await self._json(session, _API + endpoint, {**params, "page": str(page)})
            except SourceError as exc:
                raise SourceError(str(exc), list(companies.values())) from exc
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise SourceError("invalid_registry_response")

            for record in data["results"]:
                # Read the entire fetched page for oppositions, including entries after limit.
                if not isinstance(record, dict):
                    raise SourceError("invalid_registry_record")
                siren = record.get("siren") or ""
                if (_SUPPRESSION_SIREN.fullmatch(siren)
                        and (record.get("opposition_diffusion_commerciale") is True
                             or record.get("statut_diffusion") == "P")):
                    self.opposed_sirens.add(siren)
                if (record.get("opposition_diffusion_commerciale") is not False
                        or record.get("statut_diffusion") != "O"
                        or record.get("etat_administratif") != "A"):
                    continue
                for row in record.get("matching_etablissements") or []:
                    company = self._to_company(record, row, geographic, naf, center)
                    if company:
                        company.record_discovery(self.name, url)
                        companies.setdefault(company.siret, company)
            if len(companies) >= limit or page >= (data.get("total_pages") or 0):
                return list(companies.values())[:limit]
        if len(companies) < limit:
            raise SourceError("registry_page_budget_exhausted", list(companies.values()))
        return list(companies.values())[:limit]

    def _to_company(self, record: dict, row: dict, geographic: dict,
                    naf: str | None, center: list | None) -> Company | None:
        siren = record.get("siren") or ""
        siret = row.get("siret") or ""
        if (not _SUPPRESSION_SIREN.fullmatch(siren) or not re.fullmatch(r"[0-9]{14}", siret)
                or not siret.startswith(siren) or row.get("etat_administratif") != "A"
                or row.get("statut_diffusion_etablissement") != "O"):
            return None
        if naf and row.get("activite_principale") != naf:
            return None
        if center is not None:
            try:
                distance = _distance_km(float(center[0]), float(center[1]),
                                        float(row["longitude"]), float(row["latitude"]))
            except (KeyError, ValueError, TypeError):
                return None
            if not distance <= self.radius_km:
                return None
        elif any(row.get(field) != geographic[key] for key, field in (
            ("code_commune", "commune"), ("code_postal", "code_postal"),
        ) if key in geographic):
            return None

        legal = record.get("nom_raison_sociale") or record.get("nom_complet")
        trade = row.get("nom_commercial") or next(iter(row.get("liste_enseignes") or []), None)
        if not (name := trade or legal):
            return None
        return Company(
            company_name=name, legal_name=legal, trade_name=trade, siren=siren, siret=siret,
            address=row.get("adresse") or None, activity_code=row.get("activite_principale"),
            commune_code=row.get("commune"), postal_code=row.get("code_postal"),
            activity_match="confirmed" if naf else "unknown",
        )

    @staticmethod
    async def _json(session, base: str, params: dict):
        url = public_url(base).with_query(params)
        for attempt in range(3):
            delay = (2 ** attempt) + random.uniform(0, 0.3)
            try:
                async with session.get(url, allow_redirects=False) as response:
                    if response.status == 200:
                        body = await bounded_body(response, 3_000_000)
                        # Cite the endpoint without retaining the full user's query.
                        return json.loads(body), base
                    error = f"provider_http_{response.status}"
                    if response.status not in {429, 500, 502, 503, 504}:
                        raise SourceError(error)
                    if response.status == 429:
                        retry = response.headers.get("Retry-After")
                        if retry is not None and (not retry.isdecimal() or len(retry) > 2 or int(retry) > 10):
                            raise SourceError(error)
                        if retry:
                            delay = max(delay, int(retry))
            except (TimeoutError, aiohttp.ClientConnectionError) as exc:
                if isinstance(exc, aiohttp.ClientSSLError):
                    raise SourceError("provider_tls_error") from exc
                error = "provider_connection_error"
            except (FetchError, ValueError) as exc:
                raise SourceError("invalid_provider_response") from exc
            if attempt < 2:
                await asyncio.sleep(delay)
        raise SourceError(error)


def _distance_km(long_a: float, lat_a: float, long_b: float, lat_b: float) -> float:
    if not (-90 <= lat_a <= 90 and -90 <= lat_b <= 90
            and -180 <= long_a <= 180 and -180 <= long_b <= 180):
        return float("inf")
    lat_a, lat_b = radians(lat_a), radians(lat_b)
    a = sin((lat_b - lat_a) / 2) ** 2 + cos(lat_a) * cos(lat_b) * sin(radians(long_b - long_a) / 2) ** 2
    return 6371 * 2 * asin(sqrt(min(1, a)))
