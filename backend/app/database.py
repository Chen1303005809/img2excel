from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings, get_settings
from .models import Base


def build_engine(settings: Settings):
    connect_args = {"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {}
    engine = create_engine(settings.resolved_database_url, connect_args=connect_args, pool_pre_ping=True)
    if settings.resolved_database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
    return engine


settings = get_settings()
engine = build_engine(settings)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_database() -> None:
    run_migrations(settings)
    Base.metadata.create_all(engine)


def run_migrations(settings: Settings) -> None:
    """Bring the configured database to the application migration head."""
    from alembic import command
    from alembic.config import Config

    project_root = Path(__file__).resolve().parents[2]
    alembic_config = Config(str(project_root / "backend" / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(project_root / "backend" / "alembic"))
    alembic_config.set_main_option("sqlalchemy.url", settings.resolved_database_url.replace("%", "%%"))
    migration_engine = build_engine(settings)
    try:
        tables = set(inspect(migration_engine).get_table_names())
        if tables and "alembic_version" not in tables:
            # Early development builds used metadata.create_all directly.
            # Preserve such a local database and mark it at the migration
            # head instead of attempting to recreate already existing tables.
            Base.metadata.create_all(migration_engine)
            command.stamp(alembic_config, "head")
        else:
            command.upgrade(alembic_config, "head")
    finally:
        migration_engine.dispose()


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
