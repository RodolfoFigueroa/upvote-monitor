import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import ColumnElement, or_, update
from sqlmodel import Session, col, select
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from upvote_monitor.db.engine import engine
from upvote_monitor.db.models import AppSettings, MediaAttachment, ReviewItem
from upvote_monitor.enums import ApprovalStatus, DownloadStatus, DownloadStrategy
from upvote_monitor.functions import download_file_from_url
from upvote_monitor.services.event_bus import broadcast
from upvote_monitor.services.media_workflow import (
    approval_status_api,
    approved_media_attachments,
    item_has_under_review_media,
)


@dataclass
class DownloadBatchResult:
    triggered: int
    failed: int


def get_media_attachments(session: Session, item_id: str) -> list[MediaAttachment]:
    return list(
        session.exec(
            select(MediaAttachment)
            .where(MediaAttachment.item_id == item_id)
            .order_by(col(MediaAttachment.sort_index)),
        ).all(),
    )


def get_source_urls(session: Session, item_id: str) -> list[str]:
    return [
        attachment.download_url
        for attachment in get_media_attachments(session, item_id)
    ]


def get_preview_urls(session: Session, item_id: str) -> list[str]:
    return [
        attachment.preview_url or attachment.download_url
        for attachment in get_media_attachments(session, item_id)
    ]


def _broadcast_item_updated(item: ReviewItem) -> None:
    broadcast(
        "item_updated",
        {
            "item_id": item.id,
            "download_status": item.download_status.value,
            "approval_status": approval_status_api(item.approval_status),
        },
    )


def _download_ready_filter(now: datetime) -> ColumnElement[bool]:
    return or_(
        col(ReviewItem.download_ready_at).is_(None),
        col(ReviewItem.download_ready_at) <= now,
    )


def _seconds_until_download_ready(item: ReviewItem) -> float:
    if item.download_ready_at is None:
        return 0
    now = (
        datetime.now(item.download_ready_at.tzinfo)
        if item.download_ready_at.tzinfo is not None
        else datetime.now(UTC).replace(tzinfo=None)
    )
    return max((item.download_ready_at - now).total_seconds(), 0)


def claim_item_for_download(
    session: Session,
    item_id: str,
    *,
    ignore_ready_at: bool = False,
) -> ReviewItem | None:
    if item_has_under_review_media(session, item_id):
        return None

    statement = (
        update(ReviewItem)
        .where(col(ReviewItem.id) == item_id)
        .where(col(ReviewItem.approval_status) == ApprovalStatus.APPROVED)
        .where(
            col(ReviewItem.download_status).in_(
                [DownloadStatus.PENDING, DownloadStatus.FAILED],
            ),
        )
    )
    if not ignore_ready_at:
        statement = statement.where(
            _download_ready_filter(datetime.now(UTC).replace(tzinfo=None)),
        )

    result: Any = session.exec(
        statement.values(
            download_status=DownloadStatus.IN_PROGRESS,
            download_ready_at=None,
            download_error=None,
        ).execution_options(synchronize_session=False),
    )
    session.commit()

    if result.rowcount != 1:
        return None

    item = session.get(ReviewItem, item_id)
    if item is None:
        return None

    session.refresh(item)
    _broadcast_item_updated(item)
    return item


def _wait_until_download_ready(item_id: str) -> None:
    with Session(engine) as session:
        item = session.get(ReviewItem, item_id)
        if item is None:
            return
        delay_seconds = _seconds_until_download_ready(item)
    if delay_seconds > 0:
        time.sleep(delay_seconds)


def run_download_background(item_id: str, *, ignore_ready_at: bool = False) -> None:
    if not ignore_ready_at:
        _wait_until_download_ready(item_id)

    with Session(engine) as session:
        settings = session.get(AppSettings, 1)
        if settings is None:
            return
        item = claim_item_for_download(
            session,
            item_id,
            ignore_ready_at=ignore_ready_at,
        )
        if item is None:
            return
        _download_claimed_item(session, item, settings.download_base_dir)


def _download_claimed_item(
    session: Session,
    item: ReviewItem,
    download_base_dir: str,
) -> None:
    target_dir = Path(download_base_dir) / item.id

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        attachments = approved_media_attachments(session, item.id)
        _ensure_download_attachments(attachments)

        for attachment in attachments:
            target_path = target_dir / f"{attachment.sort_index:02d}"
            _download_attachment_to_path(attachment, target_path)

        item.download_status = DownloadStatus.COMPLETED
        item.downloaded_at = datetime.now(UTC)
        item.download_dir = str(target_dir.resolve())
        item.download_error = None
    except (DownloadError, OSError, RuntimeError, ValueError) as exc:
        item.download_status = DownloadStatus.FAILED
        item.download_error = str(exc)

    session.add(item)
    session.commit()
    session.refresh(item)
    _broadcast_item_updated(item)


def _ensure_download_attachments(
    attachments: list[MediaAttachment],
) -> None:
    if not attachments:
        msg = "Item has no kept media to download"
        raise RuntimeError(msg)


def _download_attachment_to_path(
    attachment: MediaAttachment,
    path: Path,
) -> None:
    if attachment.download_strategy == DownloadStrategy.HTTP:
        download_file_from_url(
            attachment.download_url,
            path,
            extension=attachment.extension,
        )
        return

    if attachment.download_strategy == DownloadStrategy.YT_DLP:
        with YoutubeDL(
            params={"outtmpl": str(path.parent / f"{path.stem}.%(ext)s")},
        ) as ydl:
            ydl.download([attachment.download_url])
        return

    msg = f"Unsupported download strategy: {attachment.download_strategy}"
    raise ValueError(msg)


def process_pending_downloads(
    session: Session,
    *,
    wait_until_ready: bool = True,
) -> DownloadBatchResult:
    settings = session.get(AppSettings, 1)
    if settings is None:
        msg = "App settings not initialized"
        raise RuntimeError(msg)

    items = session.exec(
        select(ReviewItem).where(
            col(ReviewItem.approval_status) == ApprovalStatus.APPROVED,
            col(ReviewItem.download_status).in_(
                [DownloadStatus.PENDING, DownloadStatus.FAILED],
            ),
        ),
    ).all()

    triggered = 0
    failed = 0

    for queued_item in items:
        item_id = queued_item.id
        item = claim_item_for_download(session, item_id)
        if item is None and wait_until_ready:
            pending_item = session.get(ReviewItem, item_id)
            if pending_item is not None:
                delay_seconds = _seconds_until_download_ready(pending_item)
                if delay_seconds > 0:
                    time.sleep(delay_seconds)
                    item = claim_item_for_download(session, item_id)
        if item is None:
            continue

        triggered += 1
        _download_claimed_item(session, item, settings.download_base_dir)
        session.refresh(item)
        if item.download_status == DownloadStatus.FAILED:
            failed += 1

    return DownloadBatchResult(triggered=triggered, failed=failed)
