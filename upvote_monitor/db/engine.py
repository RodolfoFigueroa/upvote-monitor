import sqlite3
from pathlib import Path
from typing import Final

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, event, inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from upvote_monitor.db.models import (
    AppSettings,
    RefreshRun,
    ReviewItem,
)
from upvote_monitor.services.preview_cache import (
    cleanup_stale_preview_cache,
    ensure_preview_cache_dir,
)
from upvote_monitor.services.source_settings import ensure_default_source_settings
from upvote_monitor.services.tagging.profiles import ensure_default_analysis_profiles

DATA_DIR = Path("/data")
DATABASE_URL = f"sqlite:///{(DATA_DIR / 'upvote_monitor.db').as_posix()}"
SQLITE_BUSY_TIMEOUT_MS: Final = 5000
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LegacyDatabaseError(RuntimeError):
    """Raised when an unversioned alpha database requires a manual reset."""


def create_sqlite_engine(
    database_url: str,
    *,
    busy_timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS,
    in_memory: bool = False,
) -> Engine:
    """Create a SQLite engine with the application's required connection policy."""
    options: dict[str, object] = {
        "connect_args": {"check_same_thread": False},
    }
    if in_memory:
        options["poolclass"] = StaticPool
    db_engine = create_engine(database_url, **options)

    @event.listens_for(db_engine, "connect")
    def _set_sqlite_pragmas(
        dbapi_connection: sqlite3.Connection,
        _record: object,
    ) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()

    @event.listens_for(db_engine, "begin")
    def _defer_foreign_keys(connection: Connection) -> None:
        # SQLModel models use scalar foreign-key IDs rather than ORM relationships,
        # so a flush may insert a child before its new parent. Constraints remain
        # enforced at transaction commit, after both rows have been written.
        connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")

    return db_engine


engine = create_sqlite_engine(DATABASE_URL)


def _has_existing_activity(session: Session) -> bool:
    has_items = session.exec(select(ReviewItem.id).limit(1)).first() is not None
    has_refresh_runs = session.exec(select(RefreshRun.id).limit(1)).first() is not None
    return has_items or has_refresh_runs


def _ensure_download_dir(download_base_dir: str) -> None:
    Path(download_base_dir).mkdir(parents=True, exist_ok=True)


def run_migrations(db_engine: Engine) -> None:
    """Upgrade a database using the versioned schema baseline."""
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    with db_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def _database_is_blank(db_engine: Engine) -> bool:
    tables = set(inspect(db_engine).get_table_names())
    if tables and "alembic_version" not in tables:
        database = db_engine.url.database or "the configured SQLite database"
        msg = (
            f"Unversioned alpha database found at {database}. "
            "Upvote Monitor cannot safely upgrade it. Stop the application, move or "
            "delete that database file, then restart to create a fresh database."
        )
        raise LegacyDatabaseError(msg)
    return not tables


def init_db() -> bool:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ensure_preview_cache_dir()
    created_database = _database_is_blank(engine)
    run_migrations(engine)

    with Session(engine) as session:
        settings = session.get(AppSettings, 1)
        created_settings = settings is None
        if settings is None:
            settings = AppSettings(id=1)
            session.add(settings)
            session.commit()
            session.refresh(settings)

        ensure_default_source_settings(session)
        ensure_default_analysis_profiles(session)
        _ensure_download_dir(settings.download_base_dir)
        cleanup_stale_preview_cache(session)

        return created_database or (
            created_settings and not _has_existing_activity(session)
        )


def get_session() -> Session:
    return Session(engine)
