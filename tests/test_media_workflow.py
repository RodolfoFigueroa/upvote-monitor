from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from upvote_monitor.api.items import reopen_rejected_media
from upvote_monitor.api.media import list_media, reopen_media, update_media
from upvote_monitor.db.models import AppSettings, MediaAttachment, ReviewItem
from upvote_monitor.enums import (
    ApprovalMode,
    ApprovalStatus,
    DownloadStatus,
    IllustrationLabel,
)
from upvote_monitor.schemas.items import MediaUpdate
from upvote_monitor.services.download import process_pending_downloads
from upvote_monitor.services.media_workflow import (
    DECISION_UNDO_GRACE_PERIOD,
    attachment_counts,
    set_media_decision,
)


@pytest.fixture
def engine() -> Iterator[Engine]:
    db_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(db_engine)
    yield db_engine
    db_engine.dispose()


def make_item(
    item_id: str,
    *,
    approval_status: ApprovalStatus = ApprovalStatus.UNDER_REVIEW,
    download_status: DownloadStatus = DownloadStatus.PENDING,
    created_at: datetime | None = None,
) -> ReviewItem:
    return ReviewItem(
        id=item_id,
        source="reddit",
        source_item_id=item_id,
        title=f"Item {item_id}",
        author_name="author",
        author_label="u/author",
        community_name="art",
        community_label="r/art",
        item_kind="gallery",
        source_url=f"https://reddit.com/r/art/comments/{item_id}/item/",
        created_at=created_at or datetime.now(UTC),
        approval_status=approval_status,
        download_status=download_status,
        raw_data_json="{}",
        media_count=2,
    )


def make_attachment(
    item_id: str,
    sort_index: int,
    *,
    approval_status: ApprovalStatus = ApprovalStatus.UNDER_REVIEW,
    illustration_label: IllustrationLabel = IllustrationLabel.UNLABELED,
) -> MediaAttachment:
    return MediaAttachment(
        item_id=item_id,
        sort_index=sort_index,
        media_type="image",
        download_url=f"https://example.com/source-{sort_index}.jpg",
        preview_url=f"https://example.com/preview-{sort_index}.jpg",
        extension=".jpg",
        approval_status=approval_status,
        illustration_label=illustration_label,
    )


def add_settings(session: Session, tmp_path: Path) -> None:
    session.add(
        AppSettings(
            id=1,
            approval_mode=ApprovalMode.MANUAL,
            refresh_cron="0 */6 * * *",
            refresh_enabled=True,
            download_base_dir=str(tmp_path),
        ),
    )


def test_media_decisions_recompute_parent_item_status(engine: Engine) -> None:
    with Session(engine) as session:
        item = make_item("mixed-decision")
        first = make_attachment(item.id, 0)
        second = make_attachment(item.id, 1)
        session.add(item)
        session.add(first)
        session.add(second)
        session.commit()
        session.refresh(first)
        session.refresh(second)

        set_media_decision(
            session,
            first,
            approval_status=ApprovalStatus.APPROVED,
            illustration_label=IllustrationLabel.YES,
        )
        session.commit()
        session.refresh(item)

        counts = attachment_counts(session, item.id)
        assert item.approval_status == ApprovalStatus.UNDER_REVIEW
        assert counts.approved == 1
        assert counts.under_review == 1
        assert counts.unlabeled == 1

        set_media_decision(session, second, approval_status=ApprovalStatus.REJECTED)
        session.commit()
        session.refresh(item)

        assert item.approval_status == ApprovalStatus.APPROVED


def test_media_api_lists_and_updates_media_workflow_state(engine: Engine) -> None:
    with Session(engine) as session:
        item = make_item("media-api")
        first = make_attachment(
            item.id,
            0,
            illustration_label=IllustrationLabel.YES,
        )
        second = make_attachment(item.id, 1)
        session.add(item)
        session.add(first)
        session.add(second)
        session.commit()
        session.refresh(second)

        listed = list_media(
            session=session,
            approval_status="under_review",
            illustration_label="yes",
            download_status=None,
            source=None,
            community=None,
            author=None,
            limit=50,
            offset=0,
            cursor=None,
        )
        assert listed.total == 1
        assert listed.media[0].illustration_label == "yes"

        assert second.id is not None
        updated = update_media(
            second.id,
            MediaUpdate(approval_status="rejected", illustration_label="no"),
            BackgroundTasks(),
            session,
        )
        assert updated.approval_status == "rejected"
        assert updated.illustration_label == "no"

        stored = session.get(MediaAttachment, second.id)
        assert stored is not None
        assert stored.approval_status == ApprovalStatus.REJECTED
        assert stored.illustration_label == IllustrationLabel.NO


def test_label_only_media_update_does_not_broadcast_queue_change(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broadcasts: list[object] = []
    monkeypatch.setattr(
        "upvote_monitor.api.media.broadcast_review_queue_changed",
        lambda *args, **kwargs: broadcasts.append((args, kwargs)),
    )

    with Session(engine) as session:
        item = make_item("label-only")
        attachment = make_attachment(item.id, 0)
        session.add(item)
        session.add(attachment)
        session.commit()
        session.refresh(attachment)

        assert attachment.id is not None
        update_media(
            attachment.id,
            MediaUpdate(illustration_label="yes"),
            BackgroundTasks(),
            session,
        )

        assert broadcasts == []


def test_approval_media_update_broadcasts_queue_change(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broadcasts: list[object] = []
    monkeypatch.setattr(
        "upvote_monitor.api.media.broadcast_review_queue_changed",
        lambda *args, **kwargs: broadcasts.append((args, kwargs)),
    )

    with Session(engine) as session:
        item = make_item("approval-broadcast")
        attachment = make_attachment(item.id, 0)
        session.add(item)
        session.add(attachment)
        session.commit()
        session.refresh(attachment)

        assert attachment.id is not None
        update_media(
            attachment.id,
            MediaUpdate(approval_status="rejected"),
            BackgroundTasks(),
            session,
        )

        assert broadcasts == [
            (
                (),
                {
                    "media_id": attachment.id,
                    "reason": "media_decision",
                },
            ),
        ]


def test_media_api_preserves_preview_index_for_gallery_media(engine: Engine) -> None:
    with Session(engine) as session:
        item = make_item("gallery-previews")
        session.add(item)
        session.add(make_attachment(item.id, 0))
        session.add(make_attachment(item.id, 1))
        session.commit()

        listed = list_media(
            session=session,
            approval_status="under_review",
            illustration_label=None,
            download_status=None,
            source=None,
            community=None,
            author=None,
            limit=50,
            offset=0,
            cursor=None,
        )

        assert [media.preview_url for media in listed.media] == [
            "/api/items/gallery-previews/preview/0",
            "/api/items/gallery-previews/preview/1",
        ]


def test_media_api_cursor_pages_are_ordered_and_non_overlapping(
    engine: Engine,
) -> None:
    with Session(engine) as session:
        created_at = datetime(2026, 1, 1, tzinfo=UTC)
        first_item = make_item("cursor-a", created_at=created_at)
        second_item = make_item("cursor-b", created_at=created_at)
        session.add(first_item)
        session.add(second_item)
        session.add(make_attachment(first_item.id, 0))
        session.add(make_attachment(first_item.id, 1))
        session.add(make_attachment(second_item.id, 0))
        session.commit()

        first_page = list_media(
            session=session,
            approval_status="under_review",
            illustration_label=None,
            download_status=None,
            source=None,
            community=None,
            author=None,
            limit=2,
            offset=0,
            cursor=None,
        )
        assert first_page.next_cursor is not None
        assert [(media.item_id, media.sort_index) for media in first_page.media] == [
            ("cursor-a", 0),
            ("cursor-a", 1),
        ]

        second_page = list_media(
            session=session,
            approval_status="under_review",
            illustration_label=None,
            download_status=None,
            source=None,
            community=None,
            author=None,
            limit=2,
            offset=0,
            cursor=first_page.next_cursor,
        )
        assert second_page.next_cursor is None
        assert [(media.item_id, media.sort_index) for media in second_page.media] == [
            ("cursor-b", 0),
        ]


def test_media_api_cursor_continues_after_prior_row_is_reviewed(
    engine: Engine,
) -> None:
    with Session(engine) as session:
        created_at = datetime(2026, 1, 1, tzinfo=UTC)
        item = make_item("cursor-review", created_at=created_at)
        first = make_attachment(item.id, 0)
        session.add(item)
        session.add(first)
        session.add(make_attachment(item.id, 1))
        session.add(make_attachment(item.id, 2))
        session.commit()
        session.refresh(first)

        first_page = list_media(
            session=session,
            approval_status="under_review",
            illustration_label=None,
            download_status=None,
            source=None,
            community=None,
            author=None,
            limit=1,
            offset=0,
            cursor=None,
        )
        assert first_page.next_cursor is not None

        first.approval_status = ApprovalStatus.APPROVED
        session.add(first)
        session.commit()

        second_page = list_media(
            session=session,
            approval_status="under_review",
            illustration_label=None,
            download_status=None,
            source=None,
            community=None,
            author=None,
            limit=2,
            offset=0,
            cursor=first_page.next_cursor,
        )
        assert [media.sort_index for media in second_page.media] == [1, 2]


def test_rejected_media_can_be_reopened_for_review(engine: Engine) -> None:
    with Session(engine) as session:
        item = make_item("reopen-rejected", approval_status=ApprovalStatus.REJECTED)
        attachment = make_attachment(
            item.id,
            0,
            approval_status=ApprovalStatus.REJECTED,
            illustration_label=IllustrationLabel.NO,
        )
        session.add(item)
        session.add(attachment)
        session.commit()
        session.refresh(attachment)

        assert attachment.id is not None
        reopened = reopen_media(attachment.id, session)

        stored = session.get(MediaAttachment, attachment.id)
        assert stored is not None
        assert reopened.approval_status == "under_review"
        assert stored.approval_status == ApprovalStatus.UNDER_REVIEW
        assert stored.illustration_label == IllustrationLabel.NO
        assert stored.decided_at is None
        stored_item = session.get(ReviewItem, item.id)
        assert stored_item is not None
        assert stored_item.approval_status == ApprovalStatus.UNDER_REVIEW


def test_approved_media_reopen_is_limited_to_undo_window(engine: Engine) -> None:
    with Session(engine) as session:
        recent_item = make_item(
            "approved-undo-recent",
            approval_status=ApprovalStatus.APPROVED,
        )
        recent = make_attachment(
            recent_item.id,
            0,
            approval_status=ApprovalStatus.APPROVED,
        )
        recent.decided_at = datetime.now(UTC)
        expired_item = make_item(
            "approved-undo-expired",
            approval_status=ApprovalStatus.APPROVED,
        )
        expired = make_attachment(
            expired_item.id,
            0,
            approval_status=ApprovalStatus.APPROVED,
        )
        expired.decided_at = (
            datetime.now(UTC) - DECISION_UNDO_GRACE_PERIOD - timedelta(seconds=1)
        )
        session.add(recent_item)
        session.add(expired_item)
        session.add(recent)
        session.add(expired)
        session.commit()
        session.refresh(recent)
        session.refresh(expired)

        assert recent.id is not None
        assert expired.id is not None
        assert expired.decided_at is not None
        expired_now = (
            datetime.now(expired.decided_at.tzinfo)
            if expired.decided_at.tzinfo is not None
            else datetime.now(UTC).replace(tzinfo=None)
        )
        assert expired_now - expired.decided_at > DECISION_UNDO_GRACE_PERIOD
        assert reopen_media(recent.id, session).approval_status == "under_review"
        with pytest.raises(HTTPException) as exc_info:
            reopen_media(expired.id, session)
        assert exc_info.value.status_code == 409


def test_item_reopen_only_reopens_rejected_media_and_keeps_files(
    engine: Engine,
) -> None:
    with Session(engine) as session:
        item = make_item(
            "reopen-item",
            approval_status=ApprovalStatus.APPROVED,
            download_status=DownloadStatus.COMPLETED,
        )
        item.download_dir = "/download/reopen-item"
        approved = make_attachment(
            item.id,
            0,
            approval_status=ApprovalStatus.APPROVED,
        )
        rejected = make_attachment(
            item.id,
            1,
            approval_status=ApprovalStatus.REJECTED,
        )
        session.add(item)
        session.add(approved)
        session.add(rejected)
        session.commit()
        session.refresh(approved)
        session.refresh(rejected)

        reopened = reopen_rejected_media(item.id, session)
        session.refresh(approved)
        session.refresh(rejected)

        assert reopened.approval_status == "under_review"
        assert approved.approval_status == ApprovalStatus.APPROVED
        assert rejected.approval_status == ApprovalStatus.UNDER_REVIEW
        assert reopened.download_status == "pending"
        stored_item = session.get(ReviewItem, item.id)
        assert stored_item is not None
        assert stored_item.download_dir == "/download/reopen-item"


def test_newly_approved_items_wait_for_download_grace_period(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloaded: list[int] = []
    monkeypatch.setattr(
        "upvote_monitor.services.download._download_attachment_to_path",
        lambda attachment, _path: downloaded.append(attachment.sort_index),
    )

    with Session(engine) as session:
        add_settings(session, tmp_path)
        item = make_item("grace-period")
        attachment = make_attachment(item.id, 0)
        session.add(item)
        session.add(attachment)
        session.commit()
        session.refresh(attachment)

        set_media_decision(session, attachment, approval_status=ApprovalStatus.APPROVED)
        session.commit()
        session.refresh(item)

        assert item.download_ready_at is not None
        ready_now = (
            datetime.now(item.download_ready_at.tzinfo)
            if item.download_ready_at.tzinfo is not None
            else datetime.now(UTC).replace(tzinfo=None)
        )
        assert item.download_ready_at > ready_now

        early = process_pending_downloads(session, wait_until_ready=False)
        session.refresh(item)

        assert early.triggered == 0
        assert downloaded == []
        assert item.download_status == DownloadStatus.PENDING

        item.download_ready_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(item)
        session.commit()

        ready = process_pending_downloads(session)
        session.refresh(item)

        assert ready.triggered == 1
        assert downloaded == [0]
        assert item.download_status == DownloadStatus.COMPLETED


def test_downloads_include_only_kept_media(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloaded: list[int] = []

    def fake_download(attachment: MediaAttachment, path: Path) -> None:
        downloaded.append(attachment.sort_index)
        path.with_suffix(attachment.extension or "").write_text(
            f"media {attachment.sort_index}",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "upvote_monitor.services.download._download_attachment_to_path",
        fake_download,
    )

    with Session(engine) as session:
        add_settings(session, tmp_path)
        item = make_item("kept-only", approval_status=ApprovalStatus.APPROVED)
        session.add(item)
        session.add(
            make_attachment(item.id, 0, approval_status=ApprovalStatus.APPROVED),
        )
        session.add(
            make_attachment(item.id, 1, approval_status=ApprovalStatus.REJECTED),
        )
        session.add(
            make_attachment(item.id, 2, approval_status=ApprovalStatus.APPROVED),
        )
        session.commit()

        result = process_pending_downloads(session)
        session.refresh(item)

        assert result.triggered == 1
        assert result.failed == 0
        assert downloaded == [0, 2]
        assert item.download_status == DownloadStatus.COMPLETED
        assert (tmp_path / item.id / "00.jpg").is_file()
        assert not (tmp_path / item.id / "01.jpg").exists()
        assert (tmp_path / item.id / "02.jpg").is_file()


def test_partially_reviewed_items_are_not_downloaded(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloaded: list[int] = []
    monkeypatch.setattr(
        "upvote_monitor.services.download._download_attachment_to_path",
        lambda attachment, _path: downloaded.append(attachment.sort_index),
    )

    with Session(engine) as session:
        add_settings(session, tmp_path)
        item = make_item("partial", approval_status=ApprovalStatus.APPROVED)
        session.add(item)
        session.add(
            make_attachment(item.id, 0, approval_status=ApprovalStatus.APPROVED),
        )
        session.add(
            make_attachment(item.id, 1, approval_status=ApprovalStatus.UNDER_REVIEW),
        )
        session.commit()

        result = process_pending_downloads(session)
        session.refresh(item)

        assert result.triggered == 0
        assert result.failed == 0
        assert downloaded == []
        assert item.download_status == DownloadStatus.PENDING
