"""Private HTTP interface. Long-running discovery is processed by the worker."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from config.settings import database_url
from core.orchestrator import Search
from storage.repository import Repository


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    url = database_url()
    if not url:
        raise RuntimeError("PostgreSQL is required")
    app.state.repository = Repository(url)
    try:
        yield
    finally:
        await app.state.repository.close()


app = FastAPI(title="LeadMiner Core", version="2.0", lifespan=lifespan)


def repository(request: Request) -> Repository:
    return request.app.state.repository


Store = Annotated[Repository, Depends(repository)]


class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    location: str = Field(min_length=1, max_length=120)
    limit: int = Field(20, ge=1, le=200)
    radius_km: float | None = Field(None, gt=0, le=50)
    min_score: int = Field(0, ge=-2, le=11)


@app.post("/searches", status_code=202)
async def create_search(body: SearchInput, repo: Store):
    try:
        search = Search(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    identifier = await repo.create(search, worker_eligible=True)
    return {"id": identifier, "status": "pending"}


@app.get("/searches/{search_id}")
async def search_details(search_id: UUID, repo: Store):
    row = await repo.get(search_id)
    if row is None:
        raise HTTPException(404, "Search not found")
    return {
        "id": row.id, "status": row.status, "parameters": row.parameters, "metrics": row.metrics,
        "created_at": row.created_at, "completed_at": row.completed_at,
    }


@app.get("/searches/{search_id}/results")
async def search_results(
    search_id: UUID, repo: Store, limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    min_score: Annotated[int, Query(ge=-2, le=11)] = -2,
    website_status: Annotated[str | None, Query(max_length=32)] = None,
):
    search = await search_details(search_id, repo)
    rows = await repo.results(search_id, limit=limit + 1, offset=offset, min_score=min_score,
                              website_status=website_status)
    return {"status": search["status"], "items": [row.to_clean_dict() for row in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None}


@app.get("/establishments/{siret}")
async def establishment(siret: Annotated[str, Path(pattern=r"^[0-9]{14}$")], repo: Store):
    row = await repo.establishment(siret)
    if row is None:
        raise HTTPException(404, "Establishment not found")
    return row.to_clean_dict()


@app.get("/health", include_in_schema=False)
async def health(repo: Store):
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError

    from storage.schema import SearchRow

    try:
        async with repo.sessions() as db:
            await db.execute(select(SearchRow.id).limit(1))
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Database unavailable") from exc
    return {"status": "ok"}
