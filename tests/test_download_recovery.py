from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.engine import Engine
from sqlmodel import Session

from tests.test_backend_fixes import make_item
from upvote_monitor.db.models import ReviewItem
from upvote_monitor.enums import ApprovalStatus, DownloadStatus
from upvote_monitor.services.download import (
    DOWNLOAD_INTERRUPTED_ERROR,
    claim_item_for_download,
    reconcile_abandoned_downloads,
)


def test_stale_download_becomes_retryable_without_changing_approval(
    engine: Engine,
) -> None:
    stale_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
    expired_claim = str(uuid4())
    with Session(engine) as session:
        item = make_item("interrupted", download_status=DownloadStatus.IN_PROGRESS)
        item.download_claim_token = expired_claim
        item.download_claimed_at = stale_at
        item.download_heartbeat_at = stale_at
        session.add(item)
        session.commit()

        assert reconcile_abandoned_downloads(session) == 1
        recovered = session.get(ReviewItem, item.id)
        assert recovered is not None
        assert recovered.approval_status == ApprovalStatus.APPROVED
        assert recovered.download_status == DownloadStatus.FAILED
        assert recovered.download_error == DOWNLOAD_INTERRUPTED_ERROR

        reclaimed = claim_item_for_download(session, item.id)
        assert reclaimed is not None
        assert reclaimed.download_status == DownloadStatus.IN_PROGRESS
        assert reclaimed.download_claim_token not in (None, expired_claim)
