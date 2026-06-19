from datetime import datetime

from pydantic import BaseModel

from upvote_monitor.db.models import RefreshRun


class RefreshRunResponse(BaseModel):
    id: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    new_items: int
    skipped: int
    downloads_triggered: int
    downloads_failed: int
    error: str | None

    @classmethod
    def from_db(cls, run: RefreshRun) -> "RefreshRunResponse":
        return cls(
            id=run.id,
            status=run.status.value,
            started_at=run.started_at,
            finished_at=run.finished_at,
            new_items=run.new_items,
            skipped=run.skipped,
            downloads_triggered=run.downloads_triggered,
            downloads_failed=run.downloads_failed,
            error=run.error,
        )


class RefreshStartResponse(BaseModel):
    run_id: str
    status: str


class RefreshStatusResponse(BaseModel):
    is_running: bool
    latest_run: RefreshRunResponse | None
