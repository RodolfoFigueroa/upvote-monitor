import base64
import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, and_, desc, func, or_
from sqlmodel import Session, col, select
from sqlmodel.sql.expression import Select

from upvote_monitor.api.deps import get_db_session
from upvote_monitor.db.models import MediaAttachment, ReviewItem
from upvote_monitor.enums import (
    ApprovalStatus,
    DownloadStatus,
    IllustrationLabel,
    RuleTargetType,
)
from upvote_monitor.schemas.items import (
    MediaItemResponse,
    MediaListResponse,
    MediaUpdate,
)
from upvote_monitor.services.approval import normalize_rule_target
from upvote_monitor.services.download import run_download_background
from upvote_monitor.services.media_workflow import (
    ApprovalTransitionConflictError,
    reopen_media_for_review,
    set_media_decision,
)
from upvote_monitor.services.refresh_status import broadcast_review_queue_changed
from upvote_monitor.services.tagging.analysis import (
    TaggerUnavailableError,
    analyze_attachment,
)

router = APIRouter(prefix="/media", tags=["media"])

_APPROVAL_FILTER = {
    "rejected": ApprovalStatus.REJECTED,
    "approved": ApprovalStatus.APPROVED,
    "under_review": ApprovalStatus.UNDER_REVIEW,
}

_ILLUSTRATION_LABEL_FILTER = {label.value: label for label in IllustrationLabel}


class MediaListFilters(BaseModel):
    approval_status: str | None = None
    illustration_label: str | None = None
    download_status: str | None = None
    item_id: str | None = None
    media_id: int | None = None
    source: list[str] | None = None
    community: str | None = None
    author: str | None = None
    limit: int = Field(default=50, ge=1, le=120)
    offset: int = Field(default=0, ge=0)
    cursor: str | None = None


def _encode_cursor(attachment: MediaAttachment, item: ReviewItem) -> str:
    if attachment.id is None:
        msg = "Cannot encode a cursor for an unpersisted attachment"
        raise ValueError(msg)
    payload = {
        "created_at": item.created_at.isoformat(),
        "item_id": item.id,
        "sort_index": attachment.sort_index,
        "media_id": attachment.id,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> dict[str, Any]:
    try:
        padding = "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        return {
            "created_at": datetime.fromisoformat(payload["created_at"]),
            "item_id": str(payload["item_id"]),
            "sort_index": int(payload["sort_index"]),
            "media_id": int(payload["media_id"]),
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor") from exc


def _cursor_filter(cursor: str) -> ColumnElement[bool]:
    payload = _decode_cursor(cursor)
    cursor_created_at = payload["created_at"]
    cursor_item_id = payload["item_id"]
    cursor_sort_index = payload["sort_index"]
    cursor_media_id = payload["media_id"]
    created_at_col = col(ReviewItem.created_at)
    item_id_col = col(ReviewItem.id)
    sort_index_col = col(MediaAttachment.sort_index)
    media_id_col = col(MediaAttachment.id)

    return or_(
        created_at_col < cursor_created_at,
        and_(
            created_at_col == cursor_created_at,
            item_id_col > cursor_item_id,
        ),
        and_(
            created_at_col == cursor_created_at,
            item_id_col == cursor_item_id,
            sort_index_col > cursor_sort_index,
        ),
        and_(
            created_at_col == cursor_created_at,
            item_id_col == cursor_item_id,
            sort_index_col == cursor_sort_index,
            media_id_col > cursor_media_id,
        ),
    )


def _parse_approval_status(value: str | None) -> ApprovalStatus | None:
    if value is None:
        return None
    if value not in _APPROVAL_FILTER:
        raise HTTPException(status_code=422, detail="Invalid approval_status")
    return _APPROVAL_FILTER[value]


def _parse_illustration_label(value: str | None) -> IllustrationLabel | None:
    if value is None:
        return None
    if value not in _ILLUSTRATION_LABEL_FILTER:
        raise HTTPException(status_code=422, detail="Invalid illustration_label")
    return _ILLUSTRATION_LABEL_FILTER[value]


def _parse_download_status(value: str | None) -> DownloadStatus | None:
    if value is None:
        return None
    try:
        return DownloadStatus(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid download_status",
        ) from exc


def _normalized_sources(filters: MediaListFilters) -> list[str]:
    return [value.strip() for value in filters.source or [] if value.strip()]


def _normalization_source(sources: list[str]) -> str | None:
    return sources[0] if len(sources) == 1 else None


def _with_cursor(
    query: Select[tuple[MediaAttachment, ReviewItem]],
    cursor: str | None,
) -> Select[tuple[MediaAttachment, ReviewItem]]:
    if cursor is None:
        return query
    return query.where(_cursor_filter(cursor))


def _get_media_or_404(
    session: Session,
    media_id: int,
) -> tuple[MediaAttachment, ReviewItem]:
    row = session.exec(
        select(MediaAttachment, ReviewItem)
        .join(ReviewItem, col(ReviewItem.id) == col(MediaAttachment.item_id))
        .where(MediaAttachment.id == media_id),
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Media not found")
    return row


@router.get("")
def list_media(
    session: Annotated[Session, Depends(get_db_session)],
    filters: Annotated[MediaListFilters, Query()],
) -> MediaListResponse:
    query = select(MediaAttachment, ReviewItem).join(
        ReviewItem,
        col(ReviewItem.id) == col(MediaAttachment.item_id),
    )
    count_query = (
        select(func.count())
        .select_from(MediaAttachment)
        .join(
            ReviewItem,
            col(ReviewItem.id) == col(MediaAttachment.item_id),
        )
    )

    media_status = _parse_approval_status(filters.approval_status)
    if media_status is not None:
        query = query.where(MediaAttachment.approval_status == media_status)
        count_query = count_query.where(MediaAttachment.approval_status == media_status)

    label = _parse_illustration_label(filters.illustration_label)
    if label is not None:
        query = query.where(MediaAttachment.illustration_label == label)
        count_query = count_query.where(MediaAttachment.illustration_label == label)

    if filters.item_id is not None:
        query = query.where(MediaAttachment.item_id == filters.item_id)
        count_query = count_query.where(MediaAttachment.item_id == filters.item_id)

    if filters.media_id is not None:
        query = query.where(MediaAttachment.id == filters.media_id)
        count_query = count_query.where(MediaAttachment.id == filters.media_id)

    dl_status = _parse_download_status(filters.download_status)
    if dl_status is not None:
        query = query.where(ReviewItem.download_status == dl_status)
        count_query = count_query.where(ReviewItem.download_status == dl_status)

    sources = _normalized_sources(filters)
    if sources:
        source_filter = col(ReviewItem.source).in_(sources)
        query = query.where(source_filter)
        count_query = count_query.where(source_filter)

    normalization_source = _normalization_source(sources)
    if filters.community is not None:
        normalized = normalize_rule_target(
            normalization_source or "reddit",
            RuleTargetType.COMMUNITY,
            filters.community,
        )
        query = query.where(ReviewItem.community_name == normalized)
        count_query = count_query.where(ReviewItem.community_name == normalized)

    if filters.author is not None:
        normalized = normalize_rule_target(
            normalization_source or "",
            RuleTargetType.AUTHOR,
            filters.author,
        )
        query = query.where(ReviewItem.author_name == normalized)
        count_query = count_query.where(ReviewItem.author_name == normalized)

    query = _with_cursor(query, filters.cursor)

    query = query.order_by(
        desc(col(ReviewItem.created_at)),
        col(ReviewItem.id),
        col(MediaAttachment.sort_index),
        col(MediaAttachment.id),
    )

    if filters.cursor is None:
        query = query.offset(filters.offset)
    query = query.limit(filters.limit + 1)

    rows = session.exec(query).all()
    returned_rows = rows[: filters.limit]
    next_cursor = (
        _encode_cursor(*returned_rows[-1])
        if len(rows) > filters.limit and returned_rows
        else None
    )
    total = session.exec(count_query).one()
    return MediaListResponse(
        media=[
            MediaItemResponse.from_db(attachment, item, session)
            for attachment, item in returned_rows
        ],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
        next_cursor=next_cursor,
    )


@router.get("/{media_id}")
def get_media(
    media_id: int,
    session: Annotated[Session, Depends(get_db_session)],
) -> MediaItemResponse:
    attachment, item = _get_media_or_404(session, media_id)
    return MediaItemResponse.from_db(attachment, item, session)


@router.patch("/{media_id}")
def update_media(
    media_id: int,
    body: MediaUpdate,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
) -> MediaItemResponse:
    attachment, item = _get_media_or_404(session, media_id)
    approval_status = _parse_approval_status(body.approval_status)
    illustration_label = _parse_illustration_label(body.illustration_label)
    if approval_status == ApprovalStatus.UNDER_REVIEW:
        raise HTTPException(
            status_code=400,
            detail="Use the reopen endpoint to return media to review",
        )
    changed_approval = approval_status is not None

    try:
        updated_item = set_media_decision(
            session,
            attachment,
            approval_status=approval_status,
            illustration_label=illustration_label,
        )
    except ApprovalTransitionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()

    session.refresh(attachment)
    item = updated_item or item
    session.refresh(item)
    if changed_approval:
        broadcast_review_queue_changed(
            media_id=attachment.id,
            reason="media_decision",
        )

    if (
        changed_approval
        and item.approval_status == ApprovalStatus.APPROVED
        and item.download_status in (DownloadStatus.PENDING, DownloadStatus.FAILED)
    ):
        background_tasks.add_task(run_download_background, item.id)

    return MediaItemResponse.from_db(attachment, item, session)


@router.post("/{media_id}/reopen")
def reopen_media(
    media_id: int,
    session: Annotated[Session, Depends(get_db_session)],
) -> MediaItemResponse:
    attachment, item = _get_media_or_404(session, media_id)
    try:
        updated_item = reopen_media_for_review(session, attachment)
    except ApprovalTransitionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session.commit()
    session.refresh(attachment)
    item = updated_item or item
    session.refresh(item)
    broadcast_review_queue_changed(
        media_id=attachment.id,
        reason="media_reopened",
    )
    return MediaItemResponse.from_db(attachment, item, session)


@router.post("/{media_id}/analyze")
def analyze_media(
    media_id: int,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
) -> MediaItemResponse:
    attachment, item = _get_media_or_404(session, media_id)
    try:
        analyze_attachment(session, attachment)
    except TaggerUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    session.refresh(attachment)
    session.refresh(item)
    if item.approval_status == ApprovalStatus.APPROVED and item.download_status in (
        DownloadStatus.PENDING,
        DownloadStatus.FAILED,
    ):
        background_tasks.add_task(run_download_background, item.id)
    return MediaItemResponse.from_db(attachment, item, session)
