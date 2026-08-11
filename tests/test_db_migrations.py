from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text
from sqlmodel import Session, SQLModel

from upvote_monitor.db import engine as db_module
from upvote_monitor.db.engine import (
    SQLITE_BUSY_TIMEOUT_MS,
    LegacyDatabaseError,
    create_sqlite_engine,
)
from upvote_monitor.db.models import AppSettings, SourceSettings
from upvote_monitor.services import preview_cache
from upvote_monitor.services.source_settings import REDDIT_SOURCE, X_SOURCE


def _configure_isolated_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Engine:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    database_path = data_dir / "upvote_monitor.db"
    db_engine = create_sqlite_engine(f"sqlite:///{database_path.as_posix()}")
    monkeypatch.setattr(db_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(db_module, "engine", db_engine)
    monkeypatch.setattr(db_module, "_ensure_download_dir", lambda _path: None)
    monkeypatch.setattr(preview_cache, "PREVIEW_CACHE_DIR", data_dir / "previews")
    return db_engine


def test_blank_database_is_migrated_and_seeded_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_engine = _configure_isolated_startup(monkeypatch, tmp_path)
    try:
        assert db_module.init_db() is True
        with Session(db_engine) as session:
            settings = session.get(AppSettings, 1)
            assert settings is not None
            settings.refresh_cron = "15 4 * * *"
            session.add(settings)
            session.commit()
            assert session.get(SourceSettings, REDDIT_SOURCE) is not None
            assert session.get(SourceSettings, X_SOURCE) is not None

        assert db_module.init_db() is False
        with Session(db_engine) as session:
            settings = session.get(AppSettings, 1)
            assert settings is not None
            assert settings.refresh_cron == "15 4 * * *"
            assert session.scalar(text("SELECT count(*) FROM app_settings")) == 1
            assert session.scalar(text("SELECT count(*) FROM source_settings")) == 2
            assert session.scalar(text("SELECT count(*) FROM analysis_profiles")) > 0
    finally:
        db_engine.dispose()


def test_unversioned_database_requires_manual_reset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_engine = _configure_isolated_startup(monkeypatch, tmp_path)
    try:
        with db_engine.begin() as connection:
            connection.execute(text("CREATE TABLE alpha_data (id INTEGER PRIMARY KEY)"))
            connection.execute(text("INSERT INTO alpha_data VALUES (1)"))

        with pytest.raises(LegacyDatabaseError, match="move or delete"):
            db_module.init_db()

        inspector = inspect(db_engine)
        assert "alpha_data" in inspector.get_table_names()
        assert "alembic_version" not in inspector.get_table_names()
        with db_engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM alpha_data")) == 1
    finally:
        db_engine.dispose()


def test_migrated_connections_enforce_sqlite_pragmas(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert connection.scalar(text("PRAGMA busy_timeout")) == SQLITE_BUSY_TIMEOUT_MS
        assert connection.scalar(text("PRAGMA journal_mode")) in {"memory", "wal"}


def test_migration_matches_sqlmodel_metadata(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        differences = compare_metadata(context, SQLModel.metadata)

    assert differences == []

    columns = {
        table: {
            column["name"] for column in inspect(migrated_engine).get_columns(table)
        }
        for table in (
            "review_items",
            "refresh_runs",
            "analysis_profiles",
            "media_analyses",
        )
    }
    assert {
        "download_claim_token",
        "download_claimed_at",
        "download_heartbeat_at",
    } <= columns["review_items"]
    assert {"claim_token", "claimed_at", "heartbeat_at"} <= columns["refresh_runs"]
    identity_columns = {"model_revision", "model_sha256", "preprocessing_version"}
    assert identity_columns <= columns["analysis_profiles"]
    assert identity_columns <= columns["media_analyses"]
