from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, make_url

from backend.app.core.config import Settings
from backend.app.db.base import Base


logger = logging.getLogger("verapolitica.db")
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def is_sqlite(database_url: str) -> bool:
    return make_url(database_url).drivername.startswith("sqlite")


def is_postgresql(database_url: str) -> bool:
    return make_url(database_url).drivername.startswith("postgresql")


def dialect_name(database_url: str) -> str:
    driver = make_url(database_url).drivername
    if driver.startswith("sqlite"):
        return "sqlite"
    if driver.startswith("postgresql"):
        return "postgresql"
    return driver.split("+", 1)[0]


def alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPOSITORY_ROOT / "alembic"))
    if database_url is not None:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def head_revision(database_url: str | None = None) -> str | None:
    return ScriptDirectory.from_config(alembic_config(database_url)).get_current_head()


def schema_is_current(engine: Engine, database_url: str | None = None) -> bool:
    current = current_revision(engine)
    return current is not None and current == head_revision(database_url)


def prepare_sqlite_schema(engine: Engine) -> None:
    """Create missing tables for lightweight SQLite test/demo/local use."""

    Base.metadata.create_all(engine)


def prepare_runtime_schema(engine: Engine, settings: Settings) -> None:
    """Keep SQLite create_all for local convenience; never auto-migrate PostgreSQL."""

    if is_sqlite(settings.database_url):
        prepare_sqlite_schema(engine)
        return
    current = current_revision(engine)
    head = head_revision(settings.database_url)
    if current != head:
        logger.warning(
            "database schema revision %s is behind Alembic head %s; "
            "run `alembic upgrade head` before relying on this database",
            current,
            head,
        )


def require_persistent_schema(engine: Engine, settings: Settings) -> None:
    if is_sqlite(settings.database_url):
        prepare_sqlite_schema(engine)
        return
    inspector = inspect(engine)
    if "sources" not in inspector.get_table_names():
        raise RuntimeError(
            "PostgreSQL schema is missing; run `alembic upgrade head` first"
        )
    if not schema_is_current(engine, settings.database_url):
        logger.warning(
            "PostgreSQL schema revision %s is not Alembic head %s",
            current_revision(engine),
            head_revision(settings.database_url),
        )


def schema_health(engine: Engine, settings: Settings) -> dict[str, object]:
    """Public health payload. Never includes connection secrets."""

    database = "ok"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        database = "error"
    revision: str | None = None
    head: str | None = None
    try:
        revision = current_revision(engine)
        head = head_revision(settings.database_url)
    except Exception:
        logger.debug("schema revision lookup failed", exc_info=True)
    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "dialect": dialect_name(settings.database_url),
        "schema_revision": revision,
        "schema_head": head,
        "schema_current": bool(revision and head and revision == head),
        "scheduler_enabled": settings.scheduler_enabled,
    }
