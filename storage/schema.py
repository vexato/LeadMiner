"""PostgreSQL mappings for jobs, establishment identities and observations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SearchRow(Base):
    __tablename__ = "searches"
    __table_args__ = (Index("ix_search_status_created", "status", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    parameters: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    metrics: Mapped[dict | None] = mapped_column(JSONB)
    worker_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    prepared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExecutionRow(Base):
    __tablename__ = "executions"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    search_id: Mapped[UUID] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiscoveryRow(Base):
    __tablename__ = "discoveries"

    search_id: Mapped[UUID] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    snapshot: Mapped[dict] = mapped_column(JSONB)


class LegalEntity(Base):
    __tablename__ = "legal_entities"

    siren: Mapped[str] = mapped_column(String(9), primary_key=True)


class Establishment(Base):
    __tablename__ = "establishments"

    siret: Mapped[str] = mapped_column(String(14), primary_key=True)
    siren: Mapped[str] = mapped_column(ForeignKey("legal_entities.siren", ondelete="CASCADE"), index=True)


class ResultRow(Base):
    __tablename__ = "search_results"
    __table_args__ = (
        UniqueConstraint("search_id", "siret", name="uq_search_result_siret"),
        Index("ix_result_public_order", "search_id", "visible", "score", "position"),
        Index("ix_result_latest", "siret", "checked_at"),
    )

    search_id: Mapped[UUID] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    siret: Mapped[str | None] = mapped_column(ForeignKey("establishments.siret", ondelete="CASCADE"))
    snapshot: Mapped[dict] = mapped_column(JSONB)
    score: Mapped[int] = mapped_column(Integer, default=0)
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    visible: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Suppression(Base):
    __tablename__ = "suppressed_identifiers"

    # Scope is encoded by length. No names, contacts or addresses are retained.
    identifier: Mapped[str] = mapped_column(String(14), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
