from sqlalchemy import desc
from sqlmodel import Session, col, select

from upvote_monitor.db.models import RefreshRun
from upvote_monitor.enums import RefreshRunStatus
from upvote_monitor.schemas.refresh import RefreshRunResponse, RefreshStatusResponse
from upvote_monitor.services.event_bus import broadcast


def get_refresh_status(session: Session) -> RefreshStatusResponse:
    running = session.exec(
        select(RefreshRun).where(
            col(RefreshRun.status).in_(
                [RefreshRunStatus.QUEUED, RefreshRunStatus.RUNNING]
            )
        )
    ).first()
    latest = session.exec(
        select(RefreshRun).order_by(desc(col(RefreshRun.started_at)))
    ).first()

    return RefreshStatusResponse(
        is_running=running is not None,
        latest_run=RefreshRunResponse.from_db(latest) if latest else None,
    )


def broadcast_refresh_status(session: Session) -> None:
    payload = get_refresh_status(session).model_dump(mode="json")
    broadcast("refresh_status", payload)


def broadcast_review_queue_changed(
    source: str | None = None,
    target_type: str | None = None,
    target_value: str | None = None,
) -> None:
    data: dict[str, str] = {}
    if source is not None:
        data["source"] = source
    if target_type is not None:
        data["target_type"] = target_type
    if target_value is not None:
        data["target_value"] = target_value
    broadcast("review_queue_changed", data)
