"""Transactional search checkpoints, PostgreSQL job leases and suppression."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import blake2b
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.orchestrator import Discovery, Orchestrator, Search, SearchResult
from models.company import Company
from storage.schema import (
    DiscoveryRow,
    Establishment,
    ExecutionRow,
    LegalEntity,
    ResultRow,
    SearchRow,
    Suppression,
)

_TERMINAL = {"completed", "partial", "failed"}
_SUPPRESSION_LOCK = 24854522236630781


def _lease_key(search_id: UUID) -> int:
    return int.from_bytes(blake2b(search_id.bytes, digest_size=8).digest(), "big", signed=True)


def _now() -> datetime:
    return datetime.now(UTC)


class Repository:
    def __init__(self, url: str) -> None:
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("Use a PostgreSQL URL with the psycopg driver")
        self.engine = create_async_engine(url, pool_pre_ping=True, hide_parameters=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def close(self) -> None:
        await self.engine.dispose()

    async def create(self, search: Search, *, worker_eligible: bool = False) -> UUID:
        search_id = uuid4()
        async with self.sessions.begin() as db:
            db.add(SearchRow(id=search_id, worker_eligible=worker_eligible,
                             parameters=json.loads(json.dumps(asdict(search)))))
        return search_id

    async def get(self, search_id: UUID) -> SearchRow | None:
        async with self.sessions() as db:
            return await db.get(SearchRow, search_id)

    async def has_discovery(self, search_id: UUID, source: str) -> bool:
        async with self.sessions() as db:
            return await db.get(DiscoveryRow, (search_id, source)) is not None

    async def pending(self) -> list[UUID]:
        async with self.sessions() as db:
            return list(await db.scalars(
                select(SearchRow.id)
                .where(SearchRow.worker_eligible, SearchRow.status.in_(("pending", "running", "interrupted")))
                .order_by(SearchRow.created_at)
            ))

    @asynccontextmanager
    async def lease(self, search_id: UUID):
        # A dedicated connection owns the lock. Process death releases it in PostgreSQL.
        key = _lease_key(search_id)
        async with self.engine.connect() as connection:
            acquired = await connection.scalar(select(func.pg_try_advisory_lock(key)))
            await connection.commit()
            if not acquired:
                yield False
                return
            try:
                yield True
            finally:
                # Closing a SQLAlchemy connection normally returns it to the pool.
                # Explicitly release the session-level lock before it can be reused.
                try:
                    await connection.scalar(select(func.pg_advisory_unlock(key)))
                    await connection.commit()
                except BaseException:
                    await connection.invalidate()
                    raise

    async def run(self, search_id: UUID, engine: Orchestrator, *, ai: bool = False,
                  public_worker: bool = False) -> SearchResult | None:
        async with self.lease(search_id) as acquired:
            if not acquired:
                return None
            row = await self.get(search_id)
            if row is None:
                raise LookupError("Search not found")
            search = search_from_params(row.parameters)
            if public_worker and (search.sources != ("sirene",) or not row.worker_eligible):
                return None
            if row.status in _TERMINAL:
                return SearchResult(await self.results(search_id, limit=1000), row.metrics or {}, row.status,
                                    await self.results(search_id, limit=1000, refused=True))
            execution_id = uuid4()
            async with self.sessions.begin() as db:
                await db.execute(update(ExecutionRow).where(ExecutionRow.search_id == search_id,
                    ExecutionRow.status == "running").values(status="interrupted", ended_at=_now()))
                await db.execute(update(SearchRow).where(SearchRow.id == search_id).values(status="running"))
                db.add(ExecutionRow(id=execution_id, search_id=search_id, status="running"))
            journal = SearchJournal(self, search_id, execution_id)
            try:
                return await engine.execute(search, journal=journal, ai=ai)
            except (asyncio.CancelledError, KeyboardInterrupt):
                await journal.interrupt("interrupted")
                raise
            except DBAPIError:
                # A database outage can also prevent updating the run. The lease
                # and durable checkpoints still allow recovery after reconnecting.
                raise
            except Exception as exc:
                await journal.interrupt("failed", error=f"engine_error_{type(exc).__name__}")
                raise

    async def results(self, search_id: UUID, *, limit: int, offset: int = 0, min_score: int = -2,
                      website_status: str | None = None, refused: bool = False) -> list[Company]:
        visibility = ResultRow.refused if refused else ResultRow.visible
        statement = select(ResultRow.snapshot).where(
            ResultRow.search_id == search_id, visibility, ResultRow.score >= min_score,
        )
        if website_status:
            statement = statement.where(ResultRow.snapshot["website_status"].astext == website_status)
        async with self.sessions() as db:
            snapshots = await db.scalars(statement.order_by(ResultRow.score.desc(), ResultRow.position)
                                         .limit(limit).offset(offset))
            return [Company.from_dict(row) for row in snapshots]

    async def establishment(self, siret: str) -> Company | None:
        async with self.sessions() as db:
            latest = await db.scalar(
                select(ResultRow.snapshot).where(
                    ResultRow.siret == siret, ResultRow.checked_at.is_not(None), ResultRow.visible,
                ).order_by(ResultRow.checked_at.desc(), ResultRow.search_id).limit(1)
            )
        return Company.from_dict(latest) if latest else None

    async def suppress(self, identifier: str) -> None:
        if len(identifier) not in (9, 14) or not identifier.isascii() or not identifier.isdecimal():
            raise ValueError("An opposition requires a SIREN or SIRET")
        async with self.sessions.begin() as db:
            await _lock_writes(db)
            await _suppress(db, identifier)

    async def delete_search(self, search_id: UUID) -> bool:
        async with self.lease(search_id) as acquired:
            if not acquired:
                raise ValueError("Search is being processed")
            async with self.sessions.begin() as db:
                return bool(await db.scalar(delete(SearchRow).where(SearchRow.id == search_id)
                                            .returning(SearchRow.id)))


class SearchJournal:
    def __init__(self, repository: Repository, search_id: UUID, execution_id: UUID) -> None:
        self.sessions = repository.sessions
        self.id = search_id
        self.execution_id = execution_id
        self.positions: list[int] = []
        self.candidates: list[Company] = []

    async def get_discovery(self, source: str) -> Discovery | None:
        async with self.sessions() as db:
            row = await db.get(DiscoveryRow, (self.id, source))
            return Discovery.from_dict(row.snapshot) if row else None

    async def save_discovery(self, source: str, batch: Discovery) -> None:
        async with self.sessions.begin() as db:
            await _lock_writes(db)
            for siren in batch.opposed_sirens:
                await _suppress(db, siren)
            blocked = await _blocked(db, batch.companies)
            snapshot = batch.to_dict()
            snapshot["companies"] = [row for row in snapshot["companies"]
                                     if row["siret"] not in blocked and row["siren"] not in blocked]
            db.add(DiscoveryRow(search_id=self.id, source=source, snapshot=snapshot))

    async def prepare(self, companies: list[Company]) -> tuple[list[Company], set[int]]:
        async with self.sessions.begin() as db:
            await _lock_writes(db)
            search = await db.get(SearchRow, self.id)
            if not search.prepared:
                blocked = await _blocked(db, companies)
                for idx, company in enumerate(companies):
                    if company.siret in blocked or company.siren in blocked:
                        continue
                    if company.siret:
                        await db.execute(insert(LegalEntity).values(siren=company.siren).on_conflict_do_nothing())
                        await db.execute(insert(Establishment).values(
                            siret=company.siret, siren=company.siren,
                        ).on_conflict_do_nothing())
                    db.add(ResultRow(search_id=self.id, position=idx, siret=company.siret,
                                     snapshot=company.to_dict()))
                search.prepared = True
            rows = list(await db.scalars(select(ResultRow).where(ResultRow.search_id == self.id)
                                         .order_by(ResultRow.position)))
        self.positions = [row.position for row in rows]
        self.candidates = [Company.from_dict(row.snapshot) for row in rows]
        return (self.candidates,
                {idx for idx, row in enumerate(rows) if row.checked_at is not None})

    async def save_result(self, idx: int, company: Company) -> None:
        async with self.sessions.begin() as db:
            await _lock_writes(db)
            await db.execute(update(ResultRow).where(
                ResultRow.search_id == self.id, ResultRow.position == self.positions[idx],
            ).values(snapshot=company.to_dict(), score=company.score, checked_at=_now()))

    async def visible_candidates(self, companies: list[Company]) -> list[Company]:
        async with self.sessions() as db:
            blocked = await _blocked(db, companies)
        return [row for row in companies if row.siren not in blocked and row.siret not in blocked]

    async def complete(self, status: str, results: list[Company], refused: list[Company], metrics: dict) -> None:
        async with self.sessions.begin() as db:
            await _lock_writes(db)
            visible_ids = {id(company) for company in results}
            refused_ids = {id(company) for company in refused}
            rows = await db.scalars(select(ResultRow).where(ResultRow.search_id == self.id))
            by_position = dict(zip(self.positions, self.candidates, strict=True))
            surviving = set()
            for row in rows:
                company = by_position[row.position]
                identity = id(company)
                surviving.add(identity)
                if identity in visible_ids or identity in refused_ids:
                    row.visible = identity in visible_ids
                    row.refused = identity in refused_ids
                    row.snapshot = company.to_dict()
            results[:] = [company for company in results if id(company) in surviving]
            refused[:] = [company for company in refused if id(company) in surviving]
            metrics["returned"] = len(results)
            search = await db.get(SearchRow, self.id)
            search.status, search.completed_at = status, _now()
            search.metrics = metrics
            await db.execute(update(ExecutionRow).where(ExecutionRow.id == self.execution_id)
                             .values(status=status, ended_at=_now()))

    async def interrupt(self, status: str, *, error: str | None = None) -> None:
        now = _now()
        changes = {"status": status}
        if error:
            changes.update(completed_at=now, metrics={"error": error})
        async with self.sessions.begin() as db:
            await db.execute(update(SearchRow).where(SearchRow.id == self.id, SearchRow.status == "running")
                             .values(**changes))
            await db.execute(update(ExecutionRow).where(ExecutionRow.id == self.execution_id,
                             ExecutionRow.status == "running").values(status=status, ended_at=now))


async def _lock_writes(db):
    await db.execute(select(func.pg_advisory_xact_lock(_SUPPRESSION_LOCK)))


async def _blocked(db, companies: list[Company]) -> set[str]:
    ids = {value for c in companies for value in (c.siren, c.siret) if value}
    return set(await db.scalars(select(Suppression.identifier).where(Suppression.identifier.in_(ids))))


async def _suppress(db, identifier: str) -> None:
    new = await db.scalar(insert(Suppression).values(identifier=identifier)
                          .on_conflict_do_nothing().returning(Suppression.identifier))
    if not new:
        return
    field = "siren" if len(identifier) == 9 else "siret"
    await db.execute(delete(ResultRow).where(ResultRow.snapshot[field].astext == identifier))
    if field == "siren":
        await db.execute(delete(LegalEntity).where(LegalEntity.siren == identifier))
    else:
        await db.execute(delete(Establishment).where(Establishment.siret == identifier))
    impacted = await db.scalars(select(DiscoveryRow).where(
        DiscoveryRow.snapshot.contains({"companies": [{field: identifier}]})
    ))
    for row in impacted:
        row.snapshot = {**row.snapshot, "companies": [
            company for company in row.snapshot["companies"] if company.get(field) != identifier
        ]}


def search_from_params(data: dict) -> Search:
    return Search(**{**data, "sources": tuple(data["sources"]), "only": tuple(data["only"])})
