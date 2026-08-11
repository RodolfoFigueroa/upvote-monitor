import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import Any
from uuid import uuid4

from sqlalchemy import Connection, Engine, and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col

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
REFRESH_LEASE_DURATION = timedelta(minutes=2)
REFRESH_HEARTBEAT_INTERVAL_SECONDS = 15.0
REFRESH_INTERRUPTED_ERROR = (
    "Interrupted: application stopped before the refresh completed; start a new refresh"
)


def _format_refresh_error(exc: Exception) -> str:
    message = str(exc)
    error_type = type(exc).__name__
    return f"{error_type}: {message}" if message else error_type


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def reconcile_abandoned_refreshes(
    session: Session,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> int:
    """Fail active refresh rows whose durable lease has expired."""
    current = (now or _utc_now()).replace(tzinfo=None)
    cutoff = current - REFRESH_LEASE_DURATION
    no_heartbeat = and_(
        col(RefreshRun.heartbeat_at).is_(None),
        or_(
            col(RefreshRun.started_at).is_(None),
            col(RefreshRun.started_at) < cutoff,
        ),
    )
    statement = update(RefreshRun).where(
        col(RefreshRun.status).in_(
            [RefreshRunStatus.QUEUED, RefreshRunStatus.RUNNING],
        ),
    )
    if not force:
        statement = statement.where(
            or_(col(RefreshRun.heartbeat_at) < cutoff, no_heartbeat),
        )
    result: Any = session.exec(
        statement.values(
            status=RefreshRunStatus.FAILED,
            finished_at=current,
            error=REFRESH_INTERRUPTED_ERROR,
            claim_token=None,
            claimed_at=None,
            heartbeat_at=None,
        ).execution_options(synchronize_session=False),
    )
    session.commit()
    session.expire_all()
    return int(result.rowcount)


def create_refresh_run(session: Session) -> RefreshRun:
    reconcile_abandoned_refreshes(session)
    now = _utc_now()
    run = RefreshRun(
        status=RefreshRunStatus.QUEUED,
        started_at=now,
        heartbeat_at=now,
    )
    try:
        session.add(run)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise RefreshAlreadyRunningError from exc
    session.refresh(run)

    broadcast_refresh_status(session)
    return run


def _heartbeat_refresh(
    bind: Engine | Connection,
    run_id: str,
    claim_token: str,
) -> None:
    with Session(bind) as heartbeat_session:
        heartbeat_session.exec(
            update(RefreshRun)
            .where(
                col(RefreshRun.id) == run_id,
                col(RefreshRun.status) == RefreshRunStatus.RUNNING,
                col(RefreshRun.claim_token) == claim_token,
            )
            .values(heartbeat_at=_utc_now()),
        )
        heartbeat_session.commit()


@contextmanager
def _refresh_heartbeat(
    bind: Engine | Connection,
    run_id: str,
    claim_token: str,
) -> Iterator[None]:
    stopped = Event()

    def heartbeat_loop() -> None:
        while not stopped.wait(REFRESH_HEARTBEAT_INTERVAL_SECONDS):
            try:
                _heartbeat_refresh(bind, run_id, claim_token)
            except Exception:
                logger.exception("Could not heartbeat refresh run %s", run_id)

    thread = Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join()


def execute_refresh_run(session: Session, run_id: str) -> None:
    claim_token = str(uuid4())
    now = _utc_now()
    claimed: Any = session.exec(
        update(RefreshRun)
        .where(
            col(RefreshRun.id) == run_id,
            col(RefreshRun.status) == RefreshRunStatus.QUEUED,
        )
        .values(
            status=RefreshRunStatus.RUNNING,
            started_at=now,
            claim_token=claim_token,
            claimed_at=now,
            heartbeat_at=now,
        )
        .execution_options(synchronize_session=False),
    )
    session.commit()
    if claimed.rowcount != 1:
        return
    broadcast_refresh_status(session)

    completed = False
    values: dict[str, object]
    try:
        bind = session.get_bind()
        with _refresh_heartbeat(bind, run_id, claim_token):
            ingest_result = ingest_items(session)
            process_pending_analysis(session)
            download_result = process_pending_downloads(session)
        values = {
            "new_items": ingest_result.new_items,
            "skipped": ingest_result.skipped,
            "downloads_triggered": download_result.triggered,
            "downloads_failed": download_result.failed,
            "status": RefreshRunStatus.COMPLETED,
            "error": None,
        }
        completed = True
    except Exception as exc:
        logger.exception("Refresh run %s failed", run_id)
        values = {
            "status": RefreshRunStatus.FAILED,
            "error": _format_refresh_error(exc),
        }
    finally:
        values.update(
            finished_at=_utc_now(),
            claim_token=None,
            claimed_at=None,
            heartbeat_at=None,
        )
        finished: Any = session.exec(
            update(RefreshRun)
            .where(
                col(RefreshRun.id) == run_id,
                col(RefreshRun.status) == RefreshRunStatus.RUNNING,
                col(RefreshRun.claim_token) == claim_token,
            )
            .values(**values)
            .execution_options(synchronize_session=False),
        )
        session.commit()
        session.expire_all()
        broadcast_refresh_status(session)
        if completed and finished.rowcount == 1:
            broadcast_review_queue_changed()


def fail_queued_refresh(session: Session, run_id: str, error: str) -> bool:
    """Fail a still-queued run when submission to its executor fails."""
    result: Any = session.exec(
        update(RefreshRun)
        .where(
            col(RefreshRun.id) == run_id,
            col(RefreshRun.status) == RefreshRunStatus.QUEUED,
        )
        .values(
            status=RefreshRunStatus.FAILED,
            finished_at=_utc_now(),
            error=error,
            heartbeat_at=None,
        ),
    )
    session.commit()
    session.expire_all()
    failed = result.rowcount == 1
    if failed:
        broadcast_refresh_status(session)
    return failed
