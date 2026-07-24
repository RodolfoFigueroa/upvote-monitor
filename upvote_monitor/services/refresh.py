import logging
from datetime import UTC, datetime
from threading import Lock

from sqlmodel import Session, col, select

from upvote_monitor.db.models import RefreshRun
from upvote_monitor.enums import RefreshRunStatus
from upvote_monitor.services.download import process_pending_downloads
from upvote_monitor.services.ingest import ingest_items
from upvote_monitor.services.refresh_status import (
    broadcast_refresh_status,
    broadcast_review_queue_changed,
)
from upvote_monitor.services.tagging import process_pending_analysis


class RefreshAlreadyRunningError(Exception):
    pass


logger = logging.getLogger(__name__)
_refresh_create_lock = Lock()


def _format_refresh_error(exc: Exception) -> str:
    message = str(exc)
    error_type = type(exc).__name__
    return f"{error_type}: {message}" if message else error_type


def _has_active_refresh(session: Session) -> bool:
    active = session.exec(
        select(RefreshRun).where(
            col(RefreshRun.status).in_(
                [RefreshRunStatus.QUEUED, RefreshRunStatus.RUNNING],
            ),
        ),
    ).first()
    return active is not None


def create_refresh_run(session: Session) -> RefreshRun:
    with _refresh_create_lock:
        if _has_active_refresh(session):
            raise RefreshAlreadyRunningError

        run = RefreshRun(
            status=RefreshRunStatus.QUEUED,
            started_at=datetime.now(UTC),
        )
        session.add(run)
        session.commit()
        session.refresh(run)

    broadcast_refresh_status(session)
    return run


def execute_refresh_run(session: Session, run_id: str) -> None:
    run = session.get(RefreshRun, run_id)
    if run is None:
        return

    run.status = RefreshRunStatus.RUNNING
    run.started_at = datetime.now(UTC)
    session.add(run)
    session.commit()
    broadcast_refresh_status(session)

    completed = False
    try:
        ingest_result = ingest_items(session)
        process_pending_analysis(session)
        download_result = process_pending_downloads(session)

        run.new_items = ingest_result.new_items
        run.skipped = ingest_result.skipped
        run.downloads_triggered = download_result.triggered
        run.downloads_failed = download_result.failed
        run.status = RefreshRunStatus.COMPLETED
        completed = True
    except Exception as exc:
        logger.exception("Refresh run %s failed", run_id)
        run.status = RefreshRunStatus.FAILED
        run.error = _format_refresh_error(exc)
    finally:
        run.finished_at = datetime.now(UTC)
        session.add(run)
        session.commit()
        broadcast_refresh_status(session)
        if completed:
            broadcast_review_queue_changed()
