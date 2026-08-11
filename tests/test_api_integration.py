import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.engine import Engine
from sqlmodel import Session

from upvote_monitor.api import refresh as refresh_api
from upvote_monitor.api.deps import get_db_session
from upvote_monitor.app import create_app
from upvote_monitor.db.models import MediaAttachment, RefreshRun, ReviewItem
from upvote_monitor.enums import (
    ApprovalStatus,
    DownloadStatus,
    IllustrationLabel,
    RefreshRunStatus,
)
from upvote_monitor.services.refresh import fail_queued_refresh


class ASGITestClient:
    def __init__(self, application: FastAPI) -> None:
        self.application = application

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, str] | None = None,
    ) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.application)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await client.request(method, path, json=json)

        return asyncio.run(send())

    def get(self, path: str) -> httpx.Response:
        return self.request("GET", path)

    def post(self, path: str) -> httpx.Response:
        return self.request("POST", path)

    def patch(self, path: str, *, json: dict[str, str]) -> httpx.Response:
        return self.request("PATCH", path, json=json)


def _item(
    item_id: str,
    *,
    approval: ApprovalStatus = ApprovalStatus.UNDER_REVIEW,
    download: DownloadStatus = DownloadStatus.PENDING,
    download_dir: Path | None = None,
) -> ReviewItem:
    return ReviewItem(
        id=item_id,
        source="reddit",
        source_item_id=item_id,
        title=f"Item {item_id}",
        author_name="operator",
        community_name="local",
        item_kind="image",
        source_url=f"https://example.test/{item_id}",
        created_at=datetime.now(UTC),
        approval_status=approval,
        download_status=download,
        raw_data_json="{}",
        media_count=1,
        download_dir=str(download_dir) if download_dir else None,
    )


def _attachment(
    item_id: str,
    *,
    approval: ApprovalStatus = ApprovalStatus.UNDER_REVIEW,
) -> MediaAttachment:
    return MediaAttachment(
        item_id=item_id,
        sort_index=0,
        media_type="image",
        download_url="https://example.test/media.jpg",
        approval_status=approval,
    )


@pytest.fixture
def api_client(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> ASGITestClient:
    application = create_app()

    def isolated_session() -> Iterator[Session]:
        with Session(migrated_engine) as session:
            yield session

    application.dependency_overrides[get_db_session] = isolated_session
    monkeypatch.setattr(refresh_api, "engine", migrated_engine)
    return ASGITestClient(application)


def test_completed_decisions_conflict_but_labels_remain_editable(
    api_client: ASGITestClient,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        item = _item(
            "immutable",
            approval=ApprovalStatus.APPROVED,
            download=DownloadStatus.COMPLETED,
        )
        attachment = _attachment(item.id, approval=ApprovalStatus.APPROVED)
        session.add(item)
        session.add(attachment)
        session.commit()
        session.refresh(attachment)
        assert attachment.id is not None
        media_id = attachment.id

    response = api_client.post("/api/items/immutable/reject")
    assert response.status_code == 409
    assert "cannot be changed" in response.json()["detail"]

    response = api_client.patch(
        f"/api/media/{media_id}",
        json={"approval_status": "rejected"},
    )
    assert response.status_code == 409

    response = api_client.patch(
        f"/api/media/{media_id}",
        json={"illustration_label": "yes"},
    )
    assert response.status_code == 200
    assert response.json()["illustration_label"] == IllustrationLabel.YES.value


def test_refresh_conflict_is_returned_through_application(
    api_client: ASGITestClient,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        session.add(
            RefreshRun(
                status=RefreshRunStatus.QUEUED,
                started_at=datetime.now(UTC),
                heartbeat_at=datetime.now(UTC),
            ),
        )
        session.commit()

    response = api_client.post("/api/refresh")
    assert response.status_code == 409
    assert response.json() == {"detail": "Refresh already running"}


def test_refresh_failure_is_persisted_and_returned(
    api_client: ASGITestClient,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error_message = "source unavailable in integration test"
    persisted_error = f"RuntimeError: {error_message}"

    def fail_submitted_refresh(run_id: str) -> None:
        with Session(migrated_engine) as session:
            assert fail_queued_refresh(session, run_id, persisted_error)

    monkeypatch.setattr(refresh_api, "_run_refresh_background", fail_submitted_refresh)

    started = api_client.post("/api/refresh")
    assert started.status_code == 202
    run_id = started.json()["run_id"]

    persisted = api_client.get(f"/api/refresh/runs/{run_id}")
    assert persisted.status_code == 200
    assert persisted.json()["status"] == RefreshRunStatus.FAILED.value
    assert persisted.json()["error"] == persisted_error

    status = api_client.get("/api/refresh/status")
    assert status.status_code == 200
    assert status.json()["is_running"] is False
    assert status.json()["latest_run"]["error"] == persisted.json()["error"]


def test_archived_file_routes_enforce_state_and_filename_guards(
    api_client: ASGITestClient,
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    archived_file = archive / "00.jpg"
    archived_file.write_bytes(b"archived media")

    with Session(migrated_engine) as session:
        session.add(
            _item(
                "available",
                approval=ApprovalStatus.APPROVED,
                download=DownloadStatus.COMPLETED,
                download_dir=archive,
            ),
        )
        session.add(
            _item(
                "not-completed",
                approval=ApprovalStatus.APPROVED,
                download=DownloadStatus.FAILED,
                download_dir=archive,
            ),
        )
        session.add(
            _item(
                "not-approved",
                approval=ApprovalStatus.REJECTED,
                download=DownloadStatus.COMPLETED,
                download_dir=archive,
            ),
        )
        session.commit()

    assert api_client.get("/api/items/not-completed/files").status_code == 404
    assert api_client.get("/api/items/not-approved/files").status_code == 404
    assert api_client.get("/api/items/not-completed/media/00.jpg").status_code == 404
    assert api_client.get("/api/items/not-approved/media/00.jpg").status_code == 404

    listed = api_client.get("/api/items/available/files")
    assert listed.status_code == 200
    assert [entry["filename"] for entry in listed.json()["files"]] == ["00.jpg"]

    downloaded = api_client.get("/api/items/available/media/00.jpg")
    assert downloaded.status_code == 200
    assert downloaded.content == b"archived media"

    invalid = api_client.get("/api/items/available/media/bad%5Cname.jpg")
    assert invalid.status_code == 400
    assert invalid.json() == {"detail": "Invalid filename"}
