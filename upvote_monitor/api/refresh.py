from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlmodel import Session, col, select

from upvote_monitor.api.deps import get_db_session
from upvote_monitor.db.engine import engine
from upvote_monitor.db.models import RefreshRun
from upvote_monitor.schemas.refresh import (
    RefreshRunResponse,
    RefreshStartResponse,
    RefreshStatusResponse,
)
from upvote_monitor.services.refresh import (
    RefreshAlreadyRunningError,
    create_refresh_run,
    execute_refresh_run,
)
from upvote_monitor.services.refresh_status import get_refresh_status

router = APIRouter(prefix="/refresh", tags=["refresh"])


def _run_refresh_background(run_id: str) -> None:
    with Session(engine) as session:
        execute_refresh_run(session, run_id)


@router.post("", response_model=RefreshStartResponse, status_code=202)
def start_refresh(
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db_session),
) -> RefreshStartResponse:
    try:
        run = create_refresh_run(session)
    except RefreshAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail="Refresh already running") from exc

    background_tasks.add_task(_run_refresh_background, run.id)
    return RefreshStartResponse(run_id=run.id, status=run.status.value)


@router.get("/status", response_model=RefreshStatusResponse)
def get_refresh_status_endpoint(
    session: Session = Depends(get_db_session),
) -> RefreshStatusResponse:
    return get_refresh_status(session)


@router.get("/runs", response_model=list[RefreshRunResponse])
def list_refresh_runs(
    session: Session = Depends(get_db_session),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[RefreshRunResponse]:
    runs = session.exec(
        select(RefreshRun)
        .order_by(desc(col(RefreshRun.started_at)))
        .offset(offset)
        .limit(limit)
    ).all()
    return [RefreshRunResponse.from_db(run) for run in runs]


@router.get("/runs/{run_id}", response_model=RefreshRunResponse)
def get_refresh_run(
    run_id: str,
    session: Session = Depends(get_db_session),
) -> RefreshRunResponse:
    run = session.get(RefreshRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Refresh run not found")
    return RefreshRunResponse.from_db(run)
