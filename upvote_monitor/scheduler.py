from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlmodel import Session

from upvote_monitor.db.engine import engine
from upvote_monitor.db.models import AppSettings
from upvote_monitor.services.refresh import (
    RefreshAlreadyRunningError,
    create_refresh_run,
    execute_refresh_run,
)

JOB_ID = "scheduled_refresh"
_scheduler: BackgroundScheduler | None = None


def _execute_refresh_run(run_id: str) -> None:
    with Session(engine) as session:
        execute_refresh_run(session, run_id)


def _run_scheduled_refresh() -> None:
    with Session(engine) as session:
        try:
            run = create_refresh_run(session)
        except RefreshAlreadyRunningError:
            return
    _execute_refresh_run(run.id)


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


def reschedule_from_settings(settings: AppSettings | None = None) -> None:
    scheduler = get_scheduler()
    if scheduler.get_job(JOB_ID):
        scheduler.remove_job(JOB_ID)

    if settings is not None:
        if not settings.refresh_enabled:
            return

        scheduler.add_job(
            _run_scheduled_refresh,
            CronTrigger.from_crontab(settings.refresh_cron),
            id=JOB_ID,
            replace_existing=True,
        )
        return

    with Session(engine) as session:
        settings = session.get(AppSettings, 1)
        if settings is None or not settings.refresh_enabled:
            return

        scheduler.add_job(
            _run_scheduled_refresh,
            CronTrigger.from_crontab(settings.refresh_cron),
            id=JOB_ID,
            replace_existing=True,
        )


def start_scheduler() -> None:
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
    reschedule_from_settings()


def queue_refresh_run() -> str | None:
    with Session(engine) as session:
        try:
            run = create_refresh_run(session)
        except RefreshAlreadyRunningError:
            return None

    scheduler = get_scheduler()
    scheduler.add_job(
        _execute_refresh_run,
        DateTrigger(run_date=datetime.now(timezone.utc)),
        args=[run.id],
        id=f"refresh_{run.id}",
    )
    return run.id


def shutdown_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
