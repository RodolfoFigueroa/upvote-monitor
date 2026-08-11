import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Any
from uuid import uuid4

from sqlalchemy import ColumnElement, Connection, Engine, and_, or_, update
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

logger = logging.getLogger(__name__)
DOWNLOAD_LEASE_DURATION = timedelta(minutes=2)
DOWNLOAD_HEARTBEAT_INTERVAL_SECONDS = 15.0
DOWNLOAD_INTERRUPTED_ERROR = (
    "Interrupted: application stopped before the download completed; retry the download"
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


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def reconcile_abandoned_downloads(
    session: Session,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> int:
    """Return downloads with expired leases to the retryable failed state."""
    current = (now or _utc_now()).replace(tzinfo=None)
    cutoff = current - DOWNLOAD_LEASE_DURATION
    no_heartbeat = and_(
        col(ReviewItem.download_heartbeat_at).is_(None),
        or_(
            col(ReviewItem.download_claimed_at) < cutoff,
            and_(
                col(ReviewItem.download_claimed_at).is_(None),
                col(ReviewItem.discovered_at) < cutoff,
            ),
        ),
    )
    statement = update(ReviewItem).where(
        col(ReviewItem.download_status) == DownloadStatus.IN_PROGRESS,
    )
    if not force:
        statement = statement.where(
            or_(col(ReviewItem.download_heartbeat_at) < cutoff, no_heartbeat),
        )
    result: Any = session.exec(
        statement.values(
            download_status=DownloadStatus.FAILED,
            download_error=DOWNLOAD_INTERRUPTED_ERROR,
            download_claim_token=None,
            download_claimed_at=None,
            download_heartbeat_at=None,
        ).execution_options(synchronize_session=False),
    )
    session.commit()
    session.expire_all()
    return int(result.rowcount)


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
    reconcile_abandoned_downloads(session)
    if item_has_under_review_media(session, item_id):
        return None

    now = _utc_now()
    claim_token = str(uuid4())

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
            download_claim_token=claim_token,
            download_claimed_at=now,
            download_heartbeat_at=now,
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


def _heartbeat_download(
    bind: Engine | Connection,
    item_id: str,
    claim_token: str,
) -> None:
    with Session(bind) as heartbeat_session:
        heartbeat_session.exec(
            update(ReviewItem)
            .where(
                col(ReviewItem.id) == item_id,
                col(ReviewItem.download_status) == DownloadStatus.IN_PROGRESS,
                col(ReviewItem.download_claim_token) == claim_token,
            )
            .values(download_heartbeat_at=_utc_now()),
        )
        heartbeat_session.commit()


@contextmanager
def _download_heartbeat(
    bind: Engine | Connection,
    item_id: str,
    claim_token: str,
) -> Iterator[None]:
    stopped = Event()

    def heartbeat_loop() -> None:
        while not stopped.wait(DOWNLOAD_HEARTBEAT_INTERVAL_SECONDS):
            try:
                _heartbeat_download(bind, item_id, claim_token)
            except Exception:
                logger.exception("Could not heartbeat download for item %s", item_id)

    thread = Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join()


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
    claim_token = item.download_claim_token
    if claim_token is None:
        return
    target_dir = Path(download_base_dir) / item.id

    values: dict[str, object]
    try:
        bind = session.get_bind()
        attachments = [
            attachment.model_copy()
            for attachment in approved_media_attachments(session, item.id)
        ]
        _ensure_download_attachments(attachments)
        # Leave no read transaction open while the separate lease writer runs.
        session.commit()
        with _download_heartbeat(bind, item.id, claim_token):
            target_dir.mkdir(parents=True, exist_ok=True)
            for attachment in attachments:
                target_path = target_dir / f"{attachment.sort_index:02d}"
                _download_attachment_to_path(attachment, target_path)

        values = {
            "download_status": DownloadStatus.COMPLETED,
            "downloaded_at": _utc_now(),
            "download_dir": str(target_dir.resolve()),
            "download_error": None,
        }
    except (DownloadError, OSError, RuntimeError, ValueError) as exc:
        values = {
            "download_status": DownloadStatus.FAILED,
            "download_error": str(exc),
        }

    values.update(
        download_claim_token=None,
        download_claimed_at=None,
        download_heartbeat_at=None,
    )
    result: Any = session.exec(
        update(ReviewItem)
        .where(
            col(ReviewItem.id) == item.id,
            col(ReviewItem.download_status) == DownloadStatus.IN_PROGRESS,
            col(ReviewItem.download_claim_token) == claim_token,
        )
        .values(**values)
        .execution_options(synchronize_session=False),
    )
    session.commit()
    session.expire_all()
    if result.rowcount != 1:
        return
    refreshed_item = session.get(ReviewItem, item.id)
    if refreshed_item is None:
        return
    session.refresh(refreshed_item)
    _broadcast_item_updated(refreshed_item)


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
    reconcile_abandoned_downloads(session)
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
