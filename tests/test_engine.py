import asyncio
import csv
import json
from pathlib import Path

import pytest

from config.settings import Settings
from core.orchestrator import Orchestrator, Search
from main import main
from models.company import Company
from output.exporter import Exporter
from scrapers.base import BaseSource, SourceError
from scrapers.sirene import SireneSource


class FixtureSource(BaseSource):
    def __init__(self, name, rows):
        self.name = name
        self.rows = rows

    async def search(self, query, location, limit):
        if self.rows is None:
            raise SourceError("provider_http_429")
        return self.rows[:limit]


def test_multisource_failure_retains_other_results_and_state():
    one = Company("Atelier", address="12 rue des Quais 33000 Bordeaux", siret="11111111100010")
    engine = Orchestrator(source_factory=lambda name, _: FixtureSource(name, [one] if name == "sirene" else None))
    result = asyncio.run(engine.execute(Search("coiffure", "Bordeaux", sources=("sirene", "catalog"))))
    assert result.status == "partial"
    assert result.companies[0].enrichment_status == "no_candidate"
    assert result.companies[0].website_status == "unknown"
    assert result.metrics["sources"]["catalog"]["error"] == "provider_http_429"
    assert result.metrics["usable_records"] == 1
    assert result.companies[0].qualification["opportunity_score"] is None


@pytest.mark.parametrize("kwargs", [
    {"query": ""}, {"query": "some\ninput"}, {"limit": 0}, {"limit": 201},
    {"radius_km": float("nan")}, {"radius_km": 51}, {"min_score": 12},
])
def test_search_validation(kwargs):
    with pytest.raises(ValueError):
        Search(**{"query": "coiffure", "location": "Bordeaux", **kwargs})


def test_sirene_filters_geography_and_opposition_and_matches_local_branch(monkeypatch):
    def row(siret, **extra):
        return {"siret": siret, "commune": "33063", "etat_administratif": "A",
                "statut_diffusion_etablissement": "O", "activite_principale": "96.02A",
                "adresse": "12 rue des Quais 33000 Bordeaux", **extra}

    record = {"siren": "111111111", "statut_diffusion": "O", "etat_administratif": "A",
              "opposition_diffusion_commerciale": False, "nom_complet": "Salon", "matching_etablissements": [
        row("11111111100010"), row("11111111100028", commune="75056"),
        row("11111111100036", etat_administratif="F"),
        row("11111111100044", activite_principale="96.02B"),
    ]}

    async def provider(session, base, params):
        if "/communes" in base:
            return [{"code": "33063", "nom": "Bordeaux"}], base
        assert params["activite_principale"] == "96.02A"
        assert params["code_commune"] == "33063"
        return {"total_pages": 1, "results": [
            record, {**record, "siren": "222222222", "opposition_diffusion_commerciale": True},
        ]}, base

    source = SireneSource(Settings())
    monkeypatch.setattr(source, "_json", provider)
    [company] = asyncio.run(source.search("salons de coiffure", "Bordeaux", 5))
    assert company.siret == "11111111100010"
    assert company.activity_match == "confirmed"
    assert source.opposed_sirens == {"222222222"}


def test_export_prevents_path_and_formula_injection(tmp_path):
    out = tmp_path / "exports"
    exporter = Exporter(Settings(output_dir=str(out)))
    jpath, cpath = [Path(path) for path in exporter.export(
        [Company(" =HYPERLINK(1)")], "name", "city", "../../escaped",
    )]
    assert jpath.parent == cpath.parent == out
    assert json.loads(jpath.read_text())[0]["company_name"] == " =HYPERLINK(1)"
    with cpath.open(encoding="utf-8-sig") as file:
        assert next(csv.DictReader(file))["company_name"] == "' =HYPERLINK(1)"


def test_cli_catalog_provenance_and_exports(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DATABASE_URL_FILE", "")
    catalog = Path(__file__).parent / "fixtures" / "catalog.json"
    assert asyncio.run(main(["-q", "coiffure", "-l", "Bordeaux", "-s", "catalog",
                             "--catalog", str(catalog), "-o", str(tmp_path)])) == 0
    [path] = list(tmp_path.glob("*.json"))
    records = json.loads(path.read_text())
    assert {row["siret"] for row in records} == {"11111111100010", "11111111100028"}
    assert all(row["observations"] for row in records)


def test_enrichment_reuses_candidate_site_for_distinct_establishments(monkeypatch):
    from scrapers.website_scraper import Page, Site

    calls = []

    async def fetch(url, session):
        calls.append(url)
        await asyncio.sleep(0)
        return Site(homepage=Page(url, "<title>Salon</title>"))

    settings = Settings(max_concurrent_website_scrapers=2)
    engine = Orchestrator(settings)
    monkeypatch.setattr(engine.pipeline.website_scraper, "scrape", fetch)
    companies = [Company("Atelier", website="https://web.fr", siret=f"111111111{i:05d}")
                 for i in range(6)]
    asyncio.run(engine.pipeline.enrich_all(companies))
    assert calls == ["https://web.fr"]
    assert all(company.website_status == "candidate_reachable" for company in companies)
