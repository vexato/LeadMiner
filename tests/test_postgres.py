import asyncio
import os
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from api.app import app
from config.settings import Settings
from core.orchestrator import Orchestrator, Search
from models.company import Company
from scrapers.base import BaseSource
from storage.repository import Repository
from storage.schema import ExecutionRow, ResultRow

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def database():
    url = os.getenv("LEADMINER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set LEADMINER_TEST_DATABASE_URL to a disposable database")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DATABASE_URL", url)
        patch.delenv("DATABASE_URL_FILE", raising=False)
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        command.check(config)
        yield url


class Registry(BaseSource):
    name = "sirene"

    def __init__(self):
        self.calls = 0

    async def search(self, query, location, limit):
        self.calls += 1
        return [Company("Atelier", address=f"{idx} rue des Quais 33000 Bordeaux",
                        siren="111111111", siret=f"111111111{idx:05d}")
                for idx in range(10, 13)][:limit]


def test_checkpoints_resume_and_opposition(database, monkeypatch):
    async def exercise():
        repo = Repository(database)
        try:
            registry = Registry()
            engine = Orchestrator(Settings(max_concurrent_website_scrapers=1), source_factory=lambda *_: registry)
            search = await repo.create(Search("coiffure", "Bordeaux"))
            started = asyncio.Event()
            before = engine.pipeline.enrich_all

            async def pause(companies, *, finished, checkpoint, timings):
                await checkpoint(0, companies[0])
                started.set()
                await asyncio.Future()

            async def check_resumed(companies, *, finished, checkpoint, timings):
                assert finished == {0}
                return await before(companies, finished=finished, checkpoint=checkpoint, timings=timings)

            monkeypatch.setattr(engine.pipeline, "enrich_all", pause)
            task = asyncio.create_task(repo.run(search, engine))
            await asyncio.wait_for(started.wait(), 5)
            assert await repo.run(search, engine) is None
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert (await repo.get(search)).status == "interrupted"

            monkeypatch.setattr(engine.pipeline, "enrich_all", check_resumed)
            result = await repo.run(search, engine)
            assert result.status == "completed"
            assert len(result.companies) == 3
            assert registry.calls == 1
            assert len((await repo.run(search, engine)).companies) == 3
            async with repo.sessions() as db:
                states = await db.scalars(select(ExecutionRow.status).where(ExecutionRow.search_id == search)
                                          .order_by(ExecutionRow.started_at))
                assert list(states) == ["interrupted", "completed"]
                assert await db.scalar(select(func.count()).select_from(ResultRow)
                                       .where(ResultRow.search_id == search)) == 3

            siret = result.companies[0].siret
            assert await repo.establishment(siret)
            await repo.suppress(siret)
            assert await repo.establishment(siret) is None
            assert len(await repo.results(search, limit=10)) == 2
            monkeypatch.setattr(engine.pipeline, "enrich_all", before)
            second = await repo.create(Search("coiffure", "Bordeaux"))
            assert len((await repo.run(second, engine)).companies) == 2
            assert await repo.delete_search(second)
            assert await repo.get(second) is None
        finally:
            await repo.close()

    asyncio.run(exercise())


def test_api_creates_job_and_reads_paginated_evidence(database):
    async def exercise():
        from uuid import UUID

        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver",
        ) as client:
            assert (await client.get("/health")).status_code == 200
            assert (await client.post("/searches", json={"query": "x", "location": "y", "limit": 999})).status_code == 422
            response = await client.post("/searches", json={"query": "coiffure", "location": "Bordeaux"})
            assert response.status_code == 202
            created = response.json()["id"]
            assert (await client.get(f"/searches/{created}")).json()["status"] == "pending"

            repo = app.state.repository
            assert UUID(created) in await repo.pending()
            registry = Registry()

            class OtherRegistry(BaseSource):
                name = "sirene"

                async def search(self, query, location, limit):
                    return [Company("Atelier", address=row.address, siren="222222222",
                                    siret="222222222" + row.siret[-5:])
                            for row in await registry.search(query, location, limit)]

            engine = Orchestrator(source_factory=lambda *_: OtherRegistry())
            assert (await repo.run(UUID(created), engine, public_worker=True)).status == "completed"
            first = (await client.get(f"/searches/{created}/results?limit=1")).json()
            second = (await client.get(f"/searches/{created}/results?limit=1&offset=1")).json()
            assert first["next_offset"] == 1
            siret = first["items"][0]["siret"]
            assert siret != second["items"][0]["siret"]
            assert (await client.get(f"/establishments/{siret}")).json()["observations"]
            filtered = await client.get(f"/searches/{created}/results?website_status=official_confirmed")
            assert not filtered.json()["items"]

    asyncio.run(exercise())


def test_cli_resumes_catalog_exports_from_checkpoint_without_file(database, tmp_path):
    from main import main

    fixture = Path(__file__).parent / "fixtures" / "catalog.json"
    assert asyncio.run(main([
        "-q", "coiffure", "-l", "Bordeaux", "-s", "catalog", "--catalog", str(fixture),
        "-o", str(tmp_path),
    ])) == 0
    first = next(tmp_path.glob("*.json"))
    search_id = first.stem.rsplit("_", 1)[-1]
    fresh = tmp_path / "replayed"
    assert asyncio.run(main(["--resume", search_id, "-o", str(fresh)])) == 0
    assert first.read_bytes() == next(fresh.glob("*.json")).read_bytes()
    assert first.with_suffix(".csv").read_bytes() == next(fresh.glob("*.csv")).read_bytes()
