from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import update
from sqlmodel import Session, col, select
from yt_dlp import YoutubeDL

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
            .order_by(col(MediaAttachment.sort_index))
        ).all()
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


def claim_item_for_download(session: Session, item_id: str) -> ReviewItem | None:
    if item_has_under_review_media(session, item_id):
        return None

    result: Any = session.exec(
        update(ReviewItem)
        .where(col(ReviewItem.id) == item_id)
        .where(col(ReviewItem.approval_status) == ApprovalStatus.APPROVED)
        .where(
            col(ReviewItem.download_status).in_(
                [DownloadStatus.PENDING, DownloadStatus.FAILED]
            )
        )
        .values(download_status=DownloadStatus.IN_PROGRESS, download_error=None)
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


def run_download_background(item_id: str) -> None:
    with Session(engine) as session:
        settings = session.get(AppSettings, 1)
        if settings is None:
            return
        item = claim_item_for_download(session, item_id)
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
        if not attachments:
            raise RuntimeError("Item has no kept media to download")

        for attachment in attachments:
            target_path = target_dir / f"{attachment.sort_index:02d}"
            _download_attachment_to_path(attachment, target_path)

        item.download_status = DownloadStatus.COMPLETED
        item.downloaded_at = datetime.now(timezone.utc)
        item.download_dir = str(target_dir.resolve())
        item.download_error = None
    except Exception as exc:
        item.download_status = DownloadStatus.FAILED
        item.download_error = str(exc)

    session.add(item)
    session.commit()
    session.refresh(item)
    _broadcast_item_updated(item)


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
            params={"outtmpl": str(path.parent / f"{path.stem}.%(ext)s")}
        ) as ydl:
            ydl.download([attachment.download_url])
        return

    raise ValueError(f"Unsupported download strategy: {attachment.download_strategy}")


def process_pending_downloads(session: Session) -> DownloadBatchResult:
    settings = session.get(AppSettings, 1)
    if settings is None:
        raise RuntimeError("App settings not initialized")

    items = session.exec(
        select(ReviewItem.id).where(
            col(ReviewItem.approval_status) == ApprovalStatus.APPROVED,
            col(ReviewItem.download_status).in_(
                [DownloadStatus.PENDING, DownloadStatus.FAILED]
            ),
        )
    ).all()

    triggered = 0
    failed = 0

    for item_id in items:
        item = claim_item_for_download(session, item_id)
        if item is None:
            continue

        triggered += 1
        _download_claimed_item(session, item, settings.download_base_dir)
        session.refresh(item)
        if item.download_status == DownloadStatus.FAILED:
            failed += 1

    return DownloadBatchResult(triggered=triggered, failed=failed)
