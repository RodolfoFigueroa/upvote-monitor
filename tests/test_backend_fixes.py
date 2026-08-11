import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.engine import Engine
from sqlmodel import Session

from upvote_monitor.api.items import ItemListFilters, list_item_files, list_items
from upvote_monitor.api.settings import update_settings
from upvote_monitor.db import engine as db_engine_module
from upvote_monitor.db.models import (
    AppSettings,
    MediaAttachment,
    ReviewItem,
    SourceSettings,
)
from upvote_monitor.enums import (
    ApprovalMode,
    ApprovalStatus,
    DownloadStatus,
    RefreshRunStatus,
)
from upvote_monitor.models.metadata import (
    AnimatedImageMediaMetadata,
    best_metadata_preview_url,
)
from upvote_monitor.schemas.items import ItemDetail
from upvote_monitor.schemas.settings import SettingsUpdate
from upvote_monitor.services import preview_cache
from upvote_monitor.services.download import claim_item_for_download
from upvote_monitor.services.refresh import (
    RefreshAlreadyRunningError,
    create_refresh_run,
    execute_refresh_run,
)
from upvote_monitor.services.secrets import SecretStore, SecretStoreUnavailableError
from upvote_monitor.services.source_settings import REDDIT_SOURCE, X_SOURCE

ENCRYPTION_KEY = "test-encryption-key"


def make_item(
    item_id: str,
    *,
    source: str = "reddit",
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED,
    download_status: DownloadStatus = DownloadStatus.PENDING,
    download_dir: str | None = None,
) -> ReviewItem:
    return ReviewItem(
        id=item_id,
        source=source,
        source_item_id=item_id,
        title=f"Item {item_id}",
        author_name="author",
        author_label="u/author",
        community_name="python",
        community_label="r/python",
        item_kind="image",
        source_url=f"https://reddit.com/r/python/comments/{item_id}/item/",
        created_at=datetime.now(UTC),
        approval_status=approval_status,
        download_status=download_status,
        raw_data_json="{}",
        media_count=1,
        download_dir=download_dir,
    )


def make_attachment(item_id: str) -> MediaAttachment:
    return MediaAttachment(
        item_id=item_id,
        sort_index=0,
        media_type="image",
        download_url="https://example.com/source.jpg",
        preview_url="https://example.com/preview.jpg",
        extension=".jpg",
    )


def test_animated_metadata_preview_falls_back_to_download_url() -> None:
    metadata = AnimatedImageMediaMetadata.model_validate(
        {
            "status": "valid",
            "id": "gif-id",
            "e": "AnimatedImage",
            "m": "image/gif",
            "p": [],
            "s": {
                "x": 640,
                "y": 480,
                "gif": "https://example.com/media/image.gif",
                "mp4": "https://example.com/media/image.mp4",
            },
        },
    )

    assert str(best_metadata_preview_url(metadata)) == (
        "https://example.com/media/image.mp4"
    )


def test_invalid_refresh_cron_is_rejected_before_persistence(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
            ),
        )
        session.commit()

        with pytest.raises(ValidationError):
            SettingsUpdate.model_validate({"refresh_cron": "not a cron"})

        settings = session.get(AppSettings, 1)
        assert settings is not None
        assert settings.refresh_cron == "0 */6 * * *"


def test_download_claim_is_single_use(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(make_item("claimable"))
        session.commit()

        claimed = claim_item_for_download(session, "claimable")
        assert claimed is not None
        assert claimed.download_status == DownloadStatus.IN_PROGRESS

        assert claim_item_for_download(session, "claimable") is None


@pytest.mark.parametrize(
    ("item_id", "approval_status", "download_status"),
    [
        ("unapproved", ApprovalStatus.UNDER_REVIEW, DownloadStatus.PENDING),
        ("completed", ApprovalStatus.APPROVED, DownloadStatus.COMPLETED),
        ("in_progress", ApprovalStatus.APPROVED, DownloadStatus.IN_PROGRESS),
    ],
)
def test_download_claim_rejects_ineligible_items(
    engine: Engine,
    item_id: str,
    approval_status: ApprovalStatus,
    download_status: DownloadStatus,
) -> None:
    with Session(engine) as session:
        session.add(
            make_item(
                item_id,
                approval_status=approval_status,
                download_status=download_status,
            ),
        )
        session.commit()

        assert claim_item_for_download(session, item_id) is None


def test_active_refresh_blocks_second_refresh_creation(engine: Engine) -> None:
    with Session(engine) as session:
        first_run = create_refresh_run(session)
        assert first_run.status == RefreshRunStatus.QUEUED

        with pytest.raises(RefreshAlreadyRunningError):
            create_refresh_run(session)


def test_refresh_failure_stores_error_type_and_message(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_ingest(_session: Session) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    monkeypatch.setattr("upvote_monitor.services.refresh.ingest_items", fail_ingest)
    caplog.set_level(logging.ERROR, logger="upvote_monitor.services.refresh")

    with Session(engine) as session:
        run = create_refresh_run(session)
        execute_refresh_run(session, run.id)

        failed_run = session.get(type(run), run.id)
        assert failed_run is not None
        assert failed_run.status == RefreshRunStatus.FAILED
        assert failed_run.error == "RuntimeError: boom"
        assert any(
            record.message == f"Refresh run {run.id} failed" and record.exc_info
            for record in caplog.records
        )


def test_refresh_failure_stores_error_type_for_empty_message(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyRefreshError(Exception):
        pass

    def fail_ingest(_session: Session) -> None:
        raise EmptyRefreshError

    monkeypatch.setattr("upvote_monitor.services.refresh.ingest_items", fail_ingest)

    with Session(engine) as session:
        run = create_refresh_run(session)
        execute_refresh_run(session, run.id)

        failed_run = session.get(type(run), run.id)
        assert failed_run is not None
        assert failed_run.status == RefreshRunStatus.FAILED
        assert failed_run.error == "EmptyRefreshError"


def test_init_db_reports_new_blank_database_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    database_path = data_dir / "upvote_monitor.db"
    db_engine = db_engine_module.create_sqlite_engine(
        f"sqlite:///{database_path.as_posix()}",
    )

    monkeypatch.setattr(db_engine_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(
        db_engine_module,
        "DATABASE_URL",
        f"sqlite:///{database_path.as_posix()}",
    )
    monkeypatch.setattr(db_engine_module, "engine", db_engine)
    monkeypatch.setattr(
        db_engine_module,
        "_ensure_download_dir",
        lambda _download_base_dir: None,
    )

    monkeypatch.setattr(
        preview_cache,
        "PREVIEW_CACHE_DIR",
        data_dir / "preview-cache",
    )

    try:
        assert db_engine_module.init_db() is True
        with Session(db_engine) as session:
            assert session.get(SourceSettings, REDDIT_SOURCE) is not None
            x_settings = session.get(SourceSettings, X_SOURCE)
            assert x_settings is not None
            assert x_settings.enabled is False
        assert db_engine_module.init_db() is False
    finally:
        db_engine.dispose()


def test_file_listing_returns_safe_file_metadata(
    engine: Engine,
    tmp_path: Path,
) -> None:
    (tmp_path / "00.jpg").write_bytes(b"image")
    (tmp_path / "clip 01.mp4").write_bytes(b"video")

    with Session(engine) as session:
        session.add(make_item("media-item", download_dir=str(tmp_path)))
        session.commit()

        response = list_item_files("media-item", session)

    assert response.item_id == "media-item"
    assert [file.filename for file in response.files] == ["00.jpg", "clip 01.mp4"]
    assert [file.url for file in response.files] == [
        "/api/items/media-item/media/00.jpg",
        "/api/items/media-item/media/clip%2001.mp4",
    ]
    assert response.files[0].media_type == "image/jpeg"
    assert response.files[1].media_type == "video/mp4"
    assert str(tmp_path) not in response.model_dump_json()


def test_item_list_filters_multiple_sources(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(make_item("reddit-item", source=REDDIT_SOURCE))
        session.add(make_item("x-item", source=X_SOURCE))
        session.add(make_item("other-item", source="other"))
        session.commit()

        response = list_items(
            session=session,
            filters=ItemListFilters(source=[REDDIT_SOURCE, X_SOURCE]),
        )

    assert response.total == 2
    assert {item.id for item in response.items} == {"reddit-item", "x-item"}


def test_item_detail_uses_attachment_urls(engine: Engine) -> None:
    with Session(engine) as session:
        item = make_item("detail-item")
        session.add(item)
        session.add(make_attachment(item.id))
        session.commit()

        detail = ItemDetail.from_db(item, session)

    assert detail.preview_urls == ["https://example.com/preview.jpg"]
    assert detail.source_urls == ["https://example.com/source.jpg"]
    assert detail.media[0].download_strategy == "http"


def test_secret_store_encrypts_source_secrets(tmp_path: Path) -> None:
    secret_path = tmp_path / "secrets.enc"
    store = SecretStore(secret_key=ENCRYPTION_KEY, path=secret_path)

    store.update_source_secrets(
        REDDIT_SOURCE,
        {"username": "myusername", "session_cookie": "cookie-value"},
    )

    assert b"cookie-value" not in secret_path.read_bytes()
    assert b"myusername" not in secret_path.read_bytes()
    assert store.get_source_secrets(REDDIT_SOURCE)["username"] == "myusername"
    assert store.get_source_secrets(REDDIT_SOURCE)["session_cookie"] == "cookie-value"
    assert store.source_secret_prefix(REDDIT_SOURCE, "session_cookie") == "cook"
    assert store.source_secret_suffix(REDDIT_SOURCE, "session_cookie") == "alue"

    store.update_source_secrets(REDDIT_SOURCE, {"username": "", "session_cookie": ""})
    assert store.get_source_secrets(REDDIT_SOURCE) == {}


def test_secret_store_requires_key(tmp_path: Path) -> None:
    store = SecretStore(secret_key=None, path=tmp_path / "secrets.enc")

    assert store.available is False
    with pytest.raises(SecretStoreUnavailableError):
        store.read_all()


def test_settings_update_stores_reddit_secret_write_only(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_path = tmp_path / "secrets.enc"

    def store_factory() -> SecretStore:
        return SecretStore(secret_key=ENCRYPTION_KEY, path=secret_path)

    monkeypatch.setattr("upvote_monitor.api.settings.SecretStore", store_factory)
    probe_calls = []

    def validate_reddit_credentials(**kwargs: str) -> None:
        probe_calls.append(kwargs)

    monkeypatch.setattr(
        "upvote_monitor.api.settings.validate_reddit_credentials",
        validate_reddit_credentials,
    )

    with Session(engine) as session:
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
            ),
        )
        session.commit()

        response = update_settings(
            SettingsUpdate.model_validate(
                {
                    "sources": {
                        "reddit": {
                            "enabled": True,
                            "username": "myusername",
                            "page_limit": 5,
                            "user_agent": "agent/1.0",
                            "session_cookie": "secret-cookie",
                        },
                    },
                },
            ),
            session,
        )

        assert response.sources.reddit.username == "myusername"
        assert response.sources.reddit.page_limit == 5
        assert response.sources.reddit.session_cookie_configured is True
        assert response.sources.reddit.session_cookie_prefix == "secr"
        assert response.sources.reddit.session_cookie_suffix == "okie"
        assert "secret-cookie" not in response.model_dump_json()
        assert store_factory().get_source_secrets(REDDIT_SOURCE) == {
            "username": "myusername",
            "session_cookie": "secret-cookie",
        }
        reddit_settings = session.get(SourceSettings, REDDIT_SOURCE)
        assert reddit_settings is not None
        assert "username" not in reddit_settings.options_json
        assert probe_calls == [
            {
                "username": "myusername",
                "session_cookie": "secret-cookie",
                "user_agent": "agent/1.0",
            },
        ]

        response = update_settings(
            SettingsUpdate.model_validate(
                {"sources": {"reddit": {"enabled": False, "session_cookie": ""}}},
            ),
            session,
        )

        assert response.sources.reddit.session_cookie_configured is False
        assert response.sources.reddit.username == ""
        assert response.sources.reddit.enabled is False
        assert store_factory().get_source_secrets(REDDIT_SOURCE) == {}


def test_settings_update_stores_x_secrets_write_only(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_path = tmp_path / "secrets.enc"

    def store_factory() -> SecretStore:
        return SecretStore(secret_key=ENCRYPTION_KEY, path=secret_path)

    monkeypatch.setattr("upvote_monitor.api.settings.SecretStore", store_factory)
    probe_calls = []

    def validate_x_credentials(**kwargs: str | None) -> None:
        probe_calls.append(kwargs)

    monkeypatch.setattr(
        "upvote_monitor.api.settings.validate_x_credentials",
        validate_x_credentials,
    )

    with Session(engine) as session:
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
            ),
        )
        session.commit()

        response = update_settings(
            SettingsUpdate.model_validate(
                {
                    "sources": {
                        "x": {
                            "enabled": True,
                            "page_limit": 5,
                            "page_size": 20,
                            "user_agent": "agent/1.0",
                            "auth_token": "secret-auth",
                            "ct0": "secret-csrf",
                            "twid": "u%3D123",
                        },
                    },
                },
            ),
            session,
        )

        assert response.sources.x.enabled is True
        assert response.sources.x.auth_token_configured is True
        expected_start = "secr"
        expected_end = "auth"
        assert response.sources.x.auth_token_prefix == expected_start
        assert response.sources.x.auth_token_suffix == expected_end
        assert response.sources.x.ct0_configured is True
        assert response.sources.x.ct0_prefix == "secr"
        assert response.sources.x.ct0_suffix == "csrf"
        assert response.sources.x.twid_configured is True
        assert "secret-auth" not in response.model_dump_json()
        assert "secret-csrf" not in response.model_dump_json()
        assert probe_calls == [
            {
                "auth_token": "secret-auth",
                "ct0": "secret-csrf",
                "twid": "u%3D123",
                "bearer_token": None,
                "user_agent": "agent/1.0",
            },
        ]

        response = update_settings(
            SettingsUpdate.model_validate(
                {
                    "sources": {
                        "x": {
                            "enabled": False,
                            "auth_token": "",
                            "ct0": "",
                            "twid": "",
                        },
                    },
                },
            ),
            session,
        )

        assert response.sources.x.auth_token_configured is False
        assert response.sources.x.ct0_configured is False
        assert response.sources.x.twid_configured is False
        assert response.sources.x.enabled is False


def test_settings_update_rejects_enabled_reddit_missing_credentials(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_path = tmp_path / "secrets.enc"

    def store_factory() -> SecretStore:
        return SecretStore(secret_key=ENCRYPTION_KEY, path=secret_path)

    monkeypatch.setattr("upvote_monitor.api.settings.SecretStore", store_factory)

    def validate_reddit_credentials(**_kwargs: str) -> None:
        msg = "probe should not run with missing credentials"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "upvote_monitor.api.settings.validate_reddit_credentials",
        validate_reddit_credentials,
    )

    with Session(engine) as session:
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
            ),
        )
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            update_settings(
                SettingsUpdate.model_validate(
                    {
                        "sources": {
                            "reddit": {"enabled": True, "username": "myusername"}
                        }
                    },
                ),
                session,
            )

        assert getattr(exc_info.value, "status_code", None) == 400
        assert getattr(exc_info.value, "detail", {})["code"] == (
            "missing_source_credentials"
        )
        assert getattr(exc_info.value, "detail", {})["fields"] == ["session_cookie"]
        assert session.get(SourceSettings, REDDIT_SOURCE) is None
        assert store_factory().get_source_secrets(REDDIT_SOURCE) == {}


def test_settings_update_rejects_enabled_x_missing_twid(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_path = tmp_path / "secrets.enc"

    def store_factory() -> SecretStore:
        return SecretStore(secret_key=ENCRYPTION_KEY, path=secret_path)

    monkeypatch.setattr("upvote_monitor.api.settings.SecretStore", store_factory)

    def validate_x_credentials(**_kwargs: str | None) -> None:
        msg = "probe should not run with missing credentials"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "upvote_monitor.api.settings.validate_x_credentials",
        validate_x_credentials,
    )

    with Session(engine) as session:
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
            ),
        )
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            update_settings(
                SettingsUpdate.model_validate(
                    {
                        "sources": {
                            "x": {
                                "enabled": True,
                                "auth_token": "secret-auth",
                                "ct0": "secret-csrf",
                            },
                        },
                    },
                ),
                session,
            )

        assert getattr(exc_info.value, "status_code", None) == 400
        assert getattr(exc_info.value, "detail", {})["code"] == (
            "missing_source_credentials"
        )
        assert getattr(exc_info.value, "detail", {})["fields"] == ["twid"]
        assert session.get(SourceSettings, X_SOURCE) is None
        assert store_factory().get_source_secrets(X_SOURCE) == {}


def test_settings_update_rejects_failed_reddit_probe_without_persisting(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_path = tmp_path / "secrets.enc"

    def store_factory() -> SecretStore:
        return SecretStore(secret_key=ENCRYPTION_KEY, path=secret_path)

    monkeypatch.setattr("upvote_monitor.api.settings.SecretStore", store_factory)

    def validate_reddit_credentials(**_kwargs: str) -> None:
        msg = "bad credentials"
        raise RuntimeError(msg)

    monkeypatch.setattr(
        "upvote_monitor.api.settings.validate_reddit_credentials",
        validate_reddit_credentials,
    )

    with Session(engine) as session:
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
            ),
        )
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            update_settings(
                SettingsUpdate.model_validate(
                    {
                        "sources": {
                            "reddit": {
                                "enabled": True,
                                "username": "myusername",
                                "session_cookie": "secret-cookie",
                            },
                        },
                    },
                ),
                session,
            )

        assert getattr(exc_info.value, "status_code", None) == 400
        assert getattr(exc_info.value, "detail", {})["code"] == "source_auth_failed"
        assert session.get(SourceSettings, REDDIT_SOURCE) is None
        assert store_factory().get_source_secrets(REDDIT_SOURCE) == {}


def test_settings_update_does_not_probe_unrelated_settings(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def validate_reddit_credentials(**_kwargs: str) -> None:
        msg = "reddit probe should not run"
        raise AssertionError(msg)

    def validate_x_credentials(**_kwargs: str | None) -> None:
        msg = "x probe should not run"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "upvote_monitor.api.settings.validate_reddit_credentials",
        validate_reddit_credentials,
    )
    monkeypatch.setattr(
        "upvote_monitor.api.settings.validate_x_credentials",
        validate_x_credentials,
    )

    with Session(engine) as session:
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
            ),
        )
        session.commit()

        response = update_settings(
            SettingsUpdate.model_validate({"refresh_enabled": False}),
            session,
        )

        assert response.refresh_enabled is False


def test_settings_update_rejects_secret_without_key(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def store_factory() -> SecretStore:
        return SecretStore(secret_key=None, path=tmp_path / "secrets.enc")

    monkeypatch.setattr("upvote_monitor.api.settings.SecretStore", store_factory)

    with Session(engine) as session:
        session.add(
            AppSettings(
                id=1,
                approval_mode=ApprovalMode.MANUAL,
                refresh_cron="0 */6 * * *",
                refresh_enabled=True,
                download_base_dir="/download",
            ),
        )
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            update_settings(
                SettingsUpdate.model_validate(
                    {"sources": {"reddit": {"session_cookie": "secret-cookie"}}},
                ),
                session,
            )

        assert getattr(exc_info.value, "status_code", None) == 400
