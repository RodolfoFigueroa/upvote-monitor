from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, col, select

from upvote_monitor.db.models import MediaAttachment, ReviewItem, utc_now
from upvote_monitor.enums import ApprovalStatus, DownloadStatus, IllustrationLabel
from upvote_monitor.services.preview_cache import delete_item_preview_cache

DECISION_UNDO_GRACE_PERIOD = timedelta(seconds=8)


class ReopenMediaConflictError(Exception):
    """Raised when a media item cannot be reopened for review."""


def _elapsed_since(value: datetime) -> timedelta:
    now = (
        datetime.now(value.tzinfo)
        if value.tzinfo is not None
        else datetime.now(timezone.utc).replace(tzinfo=None)
    )
    return now - value


@dataclass(frozen=True)
class MediaDecisionCounts:
    approved: int = 0
    rejected: int = 0
    under_review: int = 0
    unlabeled: int = 0


def approval_status_api(status: ApprovalStatus) -> str:
    return {
        ApprovalStatus.REJECTED: "rejected",
        ApprovalStatus.APPROVED: "approved",
        ApprovalStatus.UNDER_REVIEW: "under_review",
    }[status]


def attachment_counts(session: Session, item_id: str) -> MediaDecisionCounts:
    attachments = session.exec(
        select(MediaAttachment).where(MediaAttachment.item_id == item_id)
    ).all()
    return MediaDecisionCounts(
        approved=sum(
            1
            for attachment in attachments
            if attachment.approval_status == ApprovalStatus.APPROVED
        ),
        rejected=sum(
            1
            for attachment in attachments
            if attachment.approval_status == ApprovalStatus.REJECTED
        ),
        under_review=sum(
            1
            for attachment in attachments
            if attachment.approval_status == ApprovalStatus.UNDER_REVIEW
        ),
        unlabeled=sum(
            1
            for attachment in attachments
            if attachment.illustration_label == IllustrationLabel.UNLABELED
        ),
    )


def recompute_item_approval_status(session: Session, item_id: str) -> ReviewItem | None:
    item = session.get(ReviewItem, item_id)
    if item is None:
        return None

    previous_status = item.approval_status
    counts = attachment_counts(session, item_id)
    if counts.under_review:
        item.approval_status = ApprovalStatus.UNDER_REVIEW
    elif counts.approved:
        item.approval_status = ApprovalStatus.APPROVED
    else:
        item.approval_status = ApprovalStatus.REJECTED

    if item.approval_status == ApprovalStatus.APPROVED:
        if (
            previous_status != ApprovalStatus.APPROVED
            and item.download_status in (DownloadStatus.PENDING, DownloadStatus.FAILED)
        ):
            item.download_ready_at = utc_now() + DECISION_UNDO_GRACE_PERIOD
    else:
        item.download_ready_at = None

    session.add(item)
    if (
        previous_status == ApprovalStatus.UNDER_REVIEW
        and item.approval_status != ApprovalStatus.UNDER_REVIEW
    ):
        delete_item_preview_cache(item.id)
    return item


def set_item_media_approval(
    session: Session,
    item: ReviewItem,
    status: ApprovalStatus,
) -> ReviewItem:
    decided_at = utc_now() if status != ApprovalStatus.UNDER_REVIEW else None
    attachments = session.exec(
        select(MediaAttachment).where(MediaAttachment.item_id == item.id)
    ).all()
    for attachment in attachments:
        attachment.approval_status = status
        attachment.decided_at = decided_at
        session.add(attachment)

    recomputed = recompute_item_approval_status(session, item.id)
    return recomputed or item


def set_media_decision(
    session: Session,
    attachment: MediaAttachment,
    *,
    approval_status: ApprovalStatus | None = None,
    illustration_label: IllustrationLabel | None = None,
) -> ReviewItem | None:
    if approval_status is not None:
        attachment.approval_status = approval_status
        attachment.decided_at = (
            utc_now() if approval_status != ApprovalStatus.UNDER_REVIEW else None
        )
    if illustration_label is not None:
        attachment.illustration_label = illustration_label

    session.add(attachment)
    session.flush()
    return recompute_item_approval_status(session, attachment.item_id)


def reopen_media_for_review(
    session: Session,
    attachment: MediaAttachment,
) -> ReviewItem | None:
    item = session.get(ReviewItem, attachment.item_id)
    if item is None:
        return None

    if item.download_status == DownloadStatus.IN_PROGRESS:
        raise ReopenMediaConflictError("Cannot reopen media while download is in progress")

    if attachment.approval_status == ApprovalStatus.APPROVED:
        decided_at = attachment.decided_at
        if decided_at is None or _elapsed_since(decided_at) > DECISION_UNDO_GRACE_PERIOD:
            raise ReopenMediaConflictError(
                "Approved media can only be reopened during the undo window"
            )

    if attachment.approval_status == ApprovalStatus.UNDER_REVIEW:
        return item

    attachment.approval_status = ApprovalStatus.UNDER_REVIEW
    attachment.decided_at = None
    session.add(attachment)

    if item.download_status == DownloadStatus.COMPLETED:
        item.download_status = DownloadStatus.PENDING
    item.download_ready_at = None
    session.add(item)
    session.flush()
    return recompute_item_approval_status(session, attachment.item_id)


def reopen_rejected_media_for_item(
    session: Session,
    item: ReviewItem,
) -> ReviewItem:
    if item.download_status == DownloadStatus.IN_PROGRESS:
        raise ReopenMediaConflictError("Cannot reopen media while download is in progress")

    attachments = session.exec(
        select(MediaAttachment)
        .where(MediaAttachment.item_id == item.id)
        .where(MediaAttachment.approval_status == ApprovalStatus.REJECTED)
    ).all()
    if not attachments:
        return item

    for attachment in attachments:
        attachment.approval_status = ApprovalStatus.UNDER_REVIEW
        attachment.decided_at = None
        session.add(attachment)

    if item.download_status == DownloadStatus.COMPLETED:
        item.download_status = DownloadStatus.PENDING
    item.download_ready_at = None
    session.add(item)
    session.flush()

    return recompute_item_approval_status(session, item.id) or item


def item_has_under_review_media(session: Session, item_id: str) -> bool:
    return (
        session.exec(
            select(MediaAttachment.id)
            .where(MediaAttachment.item_id == item_id)
            .where(MediaAttachment.approval_status == ApprovalStatus.UNDER_REVIEW)
            .limit(1)
        ).first()
        is not None
    )


def approved_media_attachments(
    session: Session,
    item_id: str,
) -> list[MediaAttachment]:
    return list(
        session.exec(
            select(MediaAttachment)
            .where(MediaAttachment.item_id == item_id)
            .where(MediaAttachment.approval_status == ApprovalStatus.APPROVED)
            .order_by(col(MediaAttachment.sort_index))
        ).all()
    )
