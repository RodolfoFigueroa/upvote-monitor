import mimetypes
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func
from sqlmodel import Session, col, select

from upvote_monitor.api.deps import get_db_session
from upvote_monitor.db.models import ReviewItem
from upvote_monitor.enums import ApprovalStatus, DownloadStatus, RuleTargetType
from upvote_monitor.schemas.items import (
    ItemDetail,
    ItemFile,
    ItemFilesResponse,
    ItemListResponse,
    ItemSummary,
)
from upvote_monitor.services.approval import normalize_rule_target
from upvote_monitor.services.download import get_preview_urls, run_download_background
from upvote_monitor.services.media_workflow import (
    ApprovalTransitionConflictError,
    reopen_rejected_media_for_item,
    set_item_media_approval,
)
from upvote_monitor.services.preview_cache import (
    PreviewCacheFetchError,
    PreviewCacheNotFoundError,
    get_or_fetch_cached_preview,
    preview_media_type,
)
from upvote_monitor.services.refresh_status import broadcast_review_queue_changed
from upvote_monitor.services.tagging.analysis import (
    TaggerUnavailableError,
    analyze_item,
)

router = APIRouter(prefix="/items", tags=["items"])

_APPROVAL_FILTER = {
    "rejected": ApprovalStatus.REJECTED,
    "approved": ApprovalStatus.APPROVED,
    "under_review": ApprovalStatus.UNDER_REVIEW,
}


class ItemListFilters(BaseModel):
    approval_status: str | None = None
    download_status: str | None = None
    source: list[str] | None = None
    community: str | None = None
    author: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


def _get_item_or_404(session: Session, item_id: str) -> ReviewItem:
    item = session.get(ReviewItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


def _file_response_item(item_id: str, path: Path) -> ItemFile:
    media_type, _ = mimetypes.guess_type(path.name)
    filename = path.name
    return ItemFile(
        filename=filename,
        url=f"/api/items/{item_id}/media/{quote(filename, safe='')}",
        media_type=media_type or "application/octet-stream",
    )


@router.get("")
def list_items(
    session: Annotated[Session, Depends(get_db_session)],
    filters: Annotated[ItemListFilters, Query()],
) -> ItemListResponse:
    query = select(ReviewItem)
    count_query = select(func.count()).select_from(ReviewItem)
    sources = [value.strip() for value in filters.source or [] if value.strip()]

    if filters.approval_status is not None:
        if filters.approval_status not in _APPROVAL_FILTER:
            raise HTTPException(status_code=422, detail="Invalid approval_status")
        status = _APPROVAL_FILTER[filters.approval_status]
        query = query.where(ReviewItem.approval_status == status)
        count_query = count_query.where(ReviewItem.approval_status == status)

    if filters.download_status is not None:
        try:
            dl_status = DownloadStatus(filters.download_status)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Invalid download_status",
            ) from exc
        query = query.where(ReviewItem.download_status == dl_status)
        count_query = count_query.where(ReviewItem.download_status == dl_status)

    if sources:
        source_filter = col(ReviewItem.source).in_(sources)
        query = query.where(source_filter)
        count_query = count_query.where(source_filter)

    normalization_source = sources[0] if len(sources) == 1 else None

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

    query = (
        query.order_by(desc(col(ReviewItem.created_at)))
        .offset(filters.offset)
        .limit(filters.limit)
    )

    items = session.exec(query).all()
    total = session.exec(count_query).one()

    return ItemListResponse(
        items=[ItemSummary.from_db(item, session) for item in items],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )


@router.get("/{item_id}")
def get_item(
    item_id: str,
    session: Annotated[Session, Depends(get_db_session)],
) -> ItemDetail:
    item = _get_item_or_404(session, item_id)
    return ItemDetail.from_db(item, session)


@router.post("/{item_id}/analyze")
def analyze_item_endpoint(
    item_id: str,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
) -> ItemDetail:
    item = _get_item_or_404(session, item_id)
    try:
        analyze_item(session, item)
    except TaggerUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    session.refresh(item)
    if item.approval_status == ApprovalStatus.APPROVED and item.download_status in (
        DownloadStatus.PENDING,
        DownloadStatus.FAILED,
    ):
        background_tasks.add_task(run_download_background, item.id)
    return ItemDetail.from_db(item, session)


@router.post("/{item_id}/approve")
def approve_item(
    item_id: str,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
) -> ItemDetail:
    item = _get_item_or_404(session, item_id)
    try:
        item = set_item_media_approval(session, item, ApprovalStatus.APPROVED)
    except ApprovalTransitionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    session.refresh(item)
    broadcast_review_queue_changed(reason="item_decision")

    if item.download_status in (DownloadStatus.PENDING, DownloadStatus.FAILED):
        background_tasks.add_task(run_download_background, item_id)
    return ItemDetail.from_db(item, session)


@router.post("/{item_id}/reject")
def reject_item(
    item_id: str,
    session: Annotated[Session, Depends(get_db_session)],
) -> ItemDetail:
    item = _get_item_or_404(session, item_id)
    try:
        item = set_item_media_approval(session, item, ApprovalStatus.REJECTED)
    except ApprovalTransitionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    session.refresh(item)
    broadcast_review_queue_changed(reason="item_decision")
    return ItemDetail.from_db(item, session)


@router.post("/{item_id}/reopen-rejected")
def reopen_rejected_media(
    item_id: str,
    session: Annotated[Session, Depends(get_db_session)],
) -> ItemDetail:
    item = _get_item_or_404(session, item_id)
    try:
        item = reopen_rejected_media_for_item(session, item)
    except ApprovalTransitionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session.commit()
    session.refresh(item)
    broadcast_review_queue_changed(reason="rejected_media_reopened")
    return ItemDetail.from_db(item, session)


@router.post("/{item_id}/retry-download")
def retry_download(
    item_id: str,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
) -> ItemDetail:
    item = _get_item_or_404(session, item_id)
    if item.approval_status != ApprovalStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Item is not approved")
    if item.download_status not in (DownloadStatus.FAILED, DownloadStatus.PENDING):
        raise HTTPException(
            status_code=400,
            detail="Download can only be retried when pending or failed",
        )

    item.download_ready_at = None
    session.add(item)
    session.commit()
    background_tasks.add_task(run_download_background, item_id, ignore_ready_at=True)
    return ItemDetail.from_db(item, session)


@router.get("/{item_id}/preview/{index}")
def get_item_preview(
    item_id: str,
    index: Annotated[int, PathParam(ge=0)],
    session: Annotated[Session, Depends(get_db_session)],
) -> FileResponse:
    item = _get_item_or_404(session, item_id)
    if item.approval_status != ApprovalStatus.UNDER_REVIEW:
        raise HTTPException(status_code=404, detail="Preview not found")

    preview_urls = get_preview_urls(session, item.id)
    if index >= len(preview_urls):
        raise HTTPException(status_code=404, detail="Preview not found")

    try:
        file_path = get_or_fetch_cached_preview(item.id, index, preview_urls[index])
    except PreviewCacheNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Preview not found") from exc
    except PreviewCacheFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return FileResponse(file_path, media_type=preview_media_type(file_path))


@router.get("/{item_id}/media/{filename}")
def get_item_media(
    item_id: str,
    filename: str,
    session: Annotated[Session, Depends(get_db_session)],
) -> FileResponse:
    if "/" in filename or "\\" in filename or filename in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    item = _get_item_or_404(session, item_id)
    if (
        item.approval_status != ApprovalStatus.APPROVED
        or item.download_status != DownloadStatus.COMPLETED
        or item.download_dir is None
    ):
        raise HTTPException(status_code=404, detail="Archived media not found")

    download_dir = Path(item.download_dir).resolve()
    file_path = (download_dir / filename).resolve()

    if not file_path.is_relative_to(download_dir):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    media_type, _ = mimetypes.guess_type(file_path.name)
    return FileResponse(file_path, media_type=media_type or "application/octet-stream")


@router.get("/{item_id}/files")
def list_item_files(
    item_id: str,
    session: Annotated[Session, Depends(get_db_session)],
) -> ItemFilesResponse:
    item = _get_item_or_404(session, item_id)
    if (
        item.approval_status != ApprovalStatus.APPROVED
        or item.download_status != DownloadStatus.COMPLETED
        or item.download_dir is None
    ):
        raise HTTPException(status_code=404, detail="Archived media not found")

    download_dir = Path(item.download_dir)
    if not download_dir.is_dir():
        raise HTTPException(status_code=404, detail="Download directory not found")

    files = sorted(
        (
            _file_response_item(item_id, path)
            for path in download_dir.iterdir()
            if path.is_file()
        ),
        key=lambda file: file.filename,
    )
    return ItemFilesResponse(item_id=item_id, files=files)
