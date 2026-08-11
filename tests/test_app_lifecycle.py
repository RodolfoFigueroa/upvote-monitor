from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, text
from sqlmodel import Session

from upvote_monitor import app as app_module
from upvote_monitor.db import engine as db_module
from upvote_monitor.db.engine import LegacyDatabaseError, create_sqlite_engine
from upvote_monitor.db.models import AppSettings, RefreshRun, ReviewItem, SourceSettings
from upvote_monitor.enums import ApprovalStatus, DownloadStatus, RefreshRunStatus
from upvote_monitor.services import preview_cache
from upvote_monitor.services.download import DOWNLOAD_INTERRUPTED_ERROR
from upvote_monitor.services.refresh import REFRESH_INTERRUPTED_ERROR
from upvote_monitor.services.source_settings import REDDIT_SOURCE, X_SOURCE


@pytest.fixture
def startup_engine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[Engine]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database_path = data_dir / "upvote_monitor.db"
    db_engine = create_sqlite_engine(f"sqlite:///{database_path.as_posix()}")
    monkeypatch.setattr(db_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(db_module, "engine", db_engine)
    monkeypatch.setattr(app_module, "engine", db_engine)
    monkeypatch.setattr(db_module, "_ensure_download_dir", lambda _path: None)
    monkeypatch.setattr(preview_cache, "PREVIEW_CACHE_DIR", data_dir / "previews")
    yield db_engine
    db_engine.dispose()


def _stale_item(item_id: str, stale_at: datetime) -> ReviewItem:
    return ReviewItem(
        id=item_id,
        source="reddit",
        source_item_id=item_id,
        title="Interrupted download",
        item_kind="image",
        source_url="https://example.test/item",
        created_at=stale_at,
        approval_status=ApprovalStatus.APPROVED,
        download_status=DownloadStatus.IN_PROGRESS,
        raw_data_json="{}",
        media_count=1,
        discovered_at=stale_at,
        download_claim_token=str(uuid4()),
        download_claimed_at=stale_at,
        download_heartbeat_at=stale_at,
    )


def test_blank_startup_migrates_seeds_queues_and_shuts_down(
    startup_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(app_module, "start_scheduler", lambda: calls.append("start"))
    monkeypatch.setattr(app_module, "queue_refresh_run", lambda: calls.append("queue"))
    monkeypatch.setattr(
        app_module,
        "shutdown_scheduler",
        lambda: calls.append("shutdown"),
    )

    with TestClient(app_module.create_app()) as client:
        assert client.get("/api/health").status_code == 200
        assert calls == ["start", "queue"]
        assert "alembic_version" in inspect(startup_engine).get_table_names()
        with Session(startup_engine) as session:
            assert session.get(AppSettings, 1) is not None
            assert session.get(SourceSettings, REDDIT_SOURCE) is not None
            assert session.get(SourceSettings, X_SOURCE) is not None

    assert calls == ["start", "queue", "shutdown"]


def test_legacy_startup_requires_reset_without_starting_scheduler(
    startup_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with startup_engine.begin() as connection:
        connection.execute(text("CREATE TABLE alpha_state (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alpha_state VALUES (1)"))

    calls: list[str] = []
    monkeypatch.setattr(app_module, "start_scheduler", lambda: calls.append("start"))
    monkeypatch.setattr(
        app_module,
        "shutdown_scheduler",
        lambda: calls.append("shutdown"),
    )

    with (
        pytest.raises(LegacyDatabaseError, match="move or delete"),
        TestClient(app_module.create_app()),
    ):
        pass

    assert calls == []
    with startup_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM alpha_state")) == 1


def test_startup_recovers_stale_work_before_scheduler(
    startup_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_module.run_migrations(startup_engine)
    stale_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
    with Session(startup_engine) as session:
        session.add(AppSettings(id=1, download_base_dir="unused-in-test"))
        refresh = RefreshRun(
            status=RefreshRunStatus.RUNNING,
            started_at=stale_at,
            claim_token=str(uuid4()),
            claimed_at=stale_at,
            heartbeat_at=stale_at,
        )
        session.add(refresh)
        session.add(_stale_item("stale-download", stale_at))
        session.commit()
        refresh_id = refresh.id

    def observe_recovery() -> None:
        with Session(startup_engine) as session:
            recovered_refresh = session.get(RefreshRun, refresh_id)
            recovered_item = session.get(ReviewItem, "stale-download")
            assert recovered_refresh is not None
            assert recovered_refresh.status == RefreshRunStatus.FAILED
            assert recovered_refresh.error == REFRESH_INTERRUPTED_ERROR
            assert recovered_item is not None
            assert recovered_item.download_status == DownloadStatus.FAILED
            assert recovered_item.download_error == DOWNLOAD_INTERRUPTED_ERROR

    calls: list[str] = []

    def start_scheduler() -> None:
        observe_recovery()
        calls.append("start")

    monkeypatch.setattr(app_module, "start_scheduler", start_scheduler)
    monkeypatch.setattr(app_module, "queue_refresh_run", lambda: calls.append("queue"))
    monkeypatch.setattr(
        app_module,
        "shutdown_scheduler",
        lambda: calls.append("shutdown"),
    )

    with TestClient(app_module.create_app()):
        assert calls == ["start"]

    assert calls == ["start", "shutdown"]


def test_scheduler_is_shut_down_when_application_context_exits(
    startup_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert startup_engine is not None
    calls: list[str] = []
    monkeypatch.setattr(app_module, "start_scheduler", lambda: calls.append("start"))
    monkeypatch.setattr(app_module, "queue_refresh_run", lambda: None)
    monkeypatch.setattr(
        app_module,
        "shutdown_scheduler",
        lambda: calls.append("shutdown"),
    )

    message = "test interruption"
    with (
        pytest.raises(RuntimeError, match=message),
        TestClient(app_module.create_app()),
    ):
        raise RuntimeError(message)

    assert calls == ["start", "shutdown"]
