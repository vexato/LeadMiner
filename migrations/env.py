"""Run migrations using a deployment-provided PostgreSQL connection URL."""

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from config.settings import database_url
from storage.schema import Base


def migrate() -> None:
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL or DATABASE_URL_FILE is required")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Migrations require PostgreSQL with psycopg")
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = create_engine(url, poolclass=NullPool, hide_parameters=True)
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
        engine.dispose()


migrate()
