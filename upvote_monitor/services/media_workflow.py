from dataclasses import dataclass

from sqlmodel import Session, col, select

from upvote_monitor.db.models import MediaAttachment, ReviewItem
from upvote_monitor.enums import ApprovalStatus, IllustrationLabel
from upvote_monitor.services.preview_cache import delete_item_preview_cache


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
    attachments = session.exec(
        select(MediaAttachment).where(MediaAttachment.item_id == item.id)
    ).all()
    for attachment in attachments:
        attachment.approval_status = status
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
    if illustration_label is not None:
        attachment.illustration_label = illustration_label

    session.add(attachment)
    session.flush()
    return recompute_item_approval_status(session, attachment.item_id)


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
