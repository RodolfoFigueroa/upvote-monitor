import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

from upvote_monitor.api import events as events_api
from upvote_monitor.db.models import AppSettings, MediaAttachment, ReviewItem
from upvote_monitor.enums import ApprovalStatus, DownloadStatus
from upvote_monitor.services import download as download_service
from upvote_monitor.services.download import process_pending_downloads
from upvote_monitor.services.event_bus import (
    set_event_loop,
    subscriber_count,
)
from upvote_monitor.services.media_workflow import set_media_decision
from upvote_monitor.services.refresh import create_refresh_run
from upvote_monitor.services.refresh_status import broadcast_review_queue_changed


def _parse_event(message: str) -> tuple[str, dict[str, Any]]:
    lines = message.strip().splitlines()
    event = lines[0].removeprefix("event: ")
    data = json.loads(lines[1].removeprefix("data: "))
    return event, data


def _add_downloadable_item(engine: Engine, download_dir: Path) -> tuple[str, int]:
    with Session(engine) as session:
        session.add(AppSettings(id=1, download_base_dir=str(download_dir)))
        item = ReviewItem(
            id="event-item",
            source="reddit",
            source_item_id="event-item",
            title="Event item",
            item_kind="image",
            source_url="https://example.test/event-item",
            created_at=datetime.now(UTC),
            approval_status=ApprovalStatus.APPROVED,
            download_status=DownloadStatus.PENDING,
            raw_data_json="{}",
            media_count=1,
        )
        attachment = MediaAttachment(
            item_id=item.id,
            sort_index=0,
            media_type="image",
            download_url="https://example.test/media.jpg",
            approval_status=ApprovalStatus.APPROVED,
        )
        session.add(item)
        session.add(attachment)
        session.commit()
        session.refresh(attachment)
        assert attachment.id is not None
        return item.id, attachment.id


def test_sse_reports_committed_refresh_queue_and_download_changes(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(events_api, "engine", migrated_engine)
    monkeypatch.setattr(
        download_service,
        "_download_attachment_to_path",
        lambda _attachment, path: path.write_bytes(b"downloaded"),
    )
    item_id, attachment_id = _add_downloadable_item(
        migrated_engine,
        tmp_path / "downloads",
    )

    async def exercise_stream() -> None:
        set_event_loop(asyncio.get_running_loop())
        stream = events_api.event_stream()
        try:
            assert _parse_event(await anext(stream)) == ("connected", {})
            initial_event, initial_data = _parse_event(await anext(stream))
            assert initial_event == "refresh_status"
            assert initial_data["is_running"] is False
            assert subscriber_count() == 1

            with Session(migrated_engine) as session:
                run = create_refresh_run(session)
                stored_run = session.get(type(run), run.id)
                assert stored_run is not None
                assert stored_run.status.value == "queued"

            refresh_event, refresh_data = _parse_event(await anext(stream))
            assert refresh_event == "refresh_status"
            assert refresh_data["is_running"] is True
            assert refresh_data["latest_run"]["id"] == run.id

            with Session(migrated_engine) as session:
                attachment = session.get(MediaAttachment, attachment_id)
                assert attachment is not None
                set_media_decision(
                    session,
                    attachment,
                    illustration_label=attachment.illustration_label,
                )
                session.commit()
                broadcast_review_queue_changed(reason="integration_test")

            queue_event, queue_data = _parse_event(await anext(stream))
            assert queue_event == "review_queue_changed"
            assert queue_data == {"reason": "integration_test"}

            with Session(migrated_engine) as session:
                result = process_pending_downloads(session, wait_until_ready=False)
                assert result.triggered == 1

            claimed_event, claimed_data = _parse_event(await anext(stream))
            assert claimed_event == "item_updated"
            assert claimed_data["item_id"] == item_id
            assert claimed_data["download_status"] == "in_progress"

            completed_event, completed_data = _parse_event(await anext(stream))
            assert completed_event == "item_updated"
            assert completed_data["download_status"] == "completed"
            with Session(migrated_engine) as session:
                stored = session.get(ReviewItem, item_id)
                assert stored is not None
                assert stored.download_status == DownloadStatus.COMPLETED
        finally:
            await stream.aclose()
            set_event_loop(None)

        assert subscriber_count() == 0

    asyncio.run(exercise_stream())


def test_sse_disconnect_removes_subscription(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(events_api, "engine", migrated_engine)

    async def connect_then_disconnect() -> None:
        set_event_loop(asyncio.get_running_loop())
        stream = events_api.event_stream()
        try:
            await anext(stream)
            assert subscriber_count() == 1
        finally:
            await stream.aclose()
            set_event_loop(None)

    asyncio.run(connect_then_disconnect())
    assert subscriber_count() == 0
