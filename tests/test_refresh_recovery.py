from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

from upvote_monitor.db.models import RefreshRun
from upvote_monitor.enums import RefreshRunStatus
from upvote_monitor.services.refresh import (
    REFRESH_INTERRUPTED_ERROR,
    RefreshAlreadyRunningError,
    create_refresh_run,
    reconcile_abandoned_refreshes,
)


def test_stale_refresh_is_failed_and_a_new_refresh_can_start(engine: Engine) -> None:
    stale_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
    expired_claim = str(uuid4())
    with Session(engine) as session:
        stale = RefreshRun(
            status=RefreshRunStatus.RUNNING,
            started_at=stale_at,
            claimed_at=stale_at,
            heartbeat_at=stale_at,
            claim_token=expired_claim,
        )
        session.add(stale)
        session.commit()

        assert reconcile_abandoned_refreshes(session) == 1
        recovered = session.get(RefreshRun, stale.id)
        assert recovered is not None
        assert recovered.status == RefreshRunStatus.FAILED
        assert recovered.error == REFRESH_INTERRUPTED_ERROR

        replacement = create_refresh_run(session)
        assert replacement.status == RefreshRunStatus.QUEUED


def test_active_refresh_uniqueness_is_enforced_by_database(engine: Engine) -> None:
    with Session(engine) as session:
        create_refresh_run(session)

    with Session(engine) as session, pytest.raises(RefreshAlreadyRunningError):
        create_refresh_run(session)
