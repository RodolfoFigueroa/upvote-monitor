from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session

from upvote_monitor.api.items import ItemListFilters, list_items
from upvote_monitor.api.media import MediaListFilters, list_media
from upvote_monitor.db.models import (
    AnalysisProfile,
    AppSettings,
    MediaAnalysis,
    MediaAttachment,
    ReviewItem,
)
from upvote_monitor.enums import AnalysisStatus, ApprovalStatus, DownloadStatus

ACTIVE_PROFILE_ID = "active-query-profile"
HISTORY_PROFILE_ID = "history-query-profile"


@contextmanager
def statement_counter(engine: Engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)


def populate_list_rows(session: Session, count: int) -> None:
    session.add(AppSettings(id=1, active_analysis_profile_id=ACTIVE_PROFILE_ID))
    for profile_id in (ACTIVE_PROFILE_ID, HISTORY_PROFILE_ID):
        session.add(
            AnalysisProfile(
                id=profile_id,
                name=profile_id,
                model_name="query-test-model",
                model_version="resolved-version",
                scoring_version="query-test-v1",
            ),
        )
    session.flush()

    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(count):
        item_id = f"query-item-{index:03d}"
        session.add(
            ReviewItem(
                id=item_id,
                source="reddit",
                source_item_id=item_id,
                title=item_id,
                author_name="query-author",
                community_name="query-community",
                item_kind="image",
                source_url=f"https://example.com/{item_id}",
                created_at=created_at - timedelta(seconds=index),
                approval_status=ApprovalStatus.UNDER_REVIEW,
                download_status=DownloadStatus.PENDING,
                raw_data_json="{}",
                media_count=1,
            ),
        )
        session.flush()
        attachment = MediaAttachment(
            item_id=item_id,
            sort_index=0,
            media_type="image",
            download_url=f"https://example.com/{item_id}.jpg",
        )
        session.add(attachment)
        session.flush()
        assert attachment.id is not None
        for profile_id, score in (
            (ACTIVE_PROFILE_ID, 0.9),
            (HISTORY_PROFILE_ID, 0.8),
        ):
            session.add(
                MediaAnalysis(
                    attachment_id=attachment.id,
                    analysis_profile_id=profile_id,
                    model_name="query-test-model",
                    model_version="resolved-version",
                    scoring_version="query-test-v1",
                    status=AnalysisStatus.COMPLETED,
                    illustration_score=score,
                    general_tags_json='{"illustration": 0.9}',
                    character_tags_json='{"character": 0.8}',
                    ratings_json='{"safe": 0.99}',
                    analyzed_at=created_at,
                ),
            )
    session.commit()
    session.expire_all()


def test_media_page_query_count_is_bounded(engine: Engine) -> None:
    with Session(engine) as session:
        populate_list_rows(session, 120)

        with statement_counter(engine) as statements:
            response = list_media(
                session=session,
                filters=MediaListFilters(limit=120),
            )

        assert len(response.media) == 120
        assert all(len(media.analyses) == 2 for media in response.media)
        assert len(statements) <= 6


def test_item_page_query_count_is_bounded(engine: Engine) -> None:
    with Session(engine) as session:
        populate_list_rows(session, 100)

        with statement_counter(engine) as statements:
            response = list_items(
                session=session,
                filters=ItemListFilters(limit=100),
            )

        assert len(response.items) == 100
        assert all(item.media_under_review_count == 1 for item in response.items)
        assert all(item.analysis_status == "completed" for item in response.items)
        assert len(statements) <= 8
