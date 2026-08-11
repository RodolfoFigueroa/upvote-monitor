from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.engine import Engine
from sqlmodel import Session

from upvote_monitor.api.items import approve_item, get_item_preview, reject_item
from upvote_monitor.db.models import (
    AppSettings,
    MediaAttachment,
    ReviewItem,
    SourceRule,
)
from upvote_monitor.enums import (
    ApprovalMode,
    ApprovalStatus,
    DownloadStatus,
    ListType,
    RuleTargetType,
)
from upvote_monitor.schemas.items import ItemSummary
from upvote_monitor.services import preview_cache
from upvote_monitor.services.approval import recompute_pending_items_for_rule


@pytest.fixture
def preview_cache_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    monkeypatch.setattr(preview_cache, "PREVIEW_CACHE_DIR", tmp_path)
    return tmp_path


def make_item(
    item_id: str,
    *,
    approval_status: ApprovalStatus = ApprovalStatus.UNDER_REVIEW,
    download_status: DownloadStatus = DownloadStatus.PENDING,
    community: str = "python",
) -> ReviewItem:
    return ReviewItem(
        id=item_id,
        source="reddit",
        source_item_id=item_id,
        title=f"Item {item_id}",
        author_name="author",
        author_label="u/author",
        community_name=community,
        community_label=f"r/{community}",
        item_kind="image",
        source_url=f"https://reddit.com/r/{community}/comments/{item_id}/item/",
        created_at=datetime.now(UTC),
        approval_status=approval_status,
        download_status=download_status,
        raw_data_json="{}",
        media_count=1,
    )


def make_attachment(
    item_id: str,
    *,
    preview_url: str = "https://example.com/preview.jpg",
) -> MediaAttachment:
    return MediaAttachment(
        item_id=item_id,
        sort_index=0,
        media_type="image",
        download_url="https://example.com/source.jpg",
        preview_url=preview_url,
        extension=".jpg",
    )


class FakeResponse:
    def __init__(
        self,
        content: bytes,
        content_type: str,
        content_length: str | None = None,
    ) -> None:
        self.content = content
        self.headers = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = content_length
        self.closed = False

    def raise_for_status(self) -> None:
        pass

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset : offset + chunk_size]

    def close(self) -> None:
        self.closed = True


def _add_settings(session: Session) -> None:
    session.add(
        AppSettings(
            id=1,
            approval_mode=ApprovalMode.MANUAL,
            refresh_cron="0 */6 * * *",
            refresh_enabled=True,
            download_base_dir="/download",
        ),
    )


def _write_cached_preview(item_id: str) -> Path:
    cache_dir = preview_cache.item_cache_dir(item_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "0.jpg"
    path.write_bytes(b"cached")
    return path


def test_under_review_image_preview_urls_are_local(engine: Engine) -> None:
    with Session(engine) as session:
        item = make_item("review-item")
        session.add(item)
        session.add(make_attachment(item.id))
        session.commit()

        summary = ItemSummary.from_db(item, session)

    assert summary.preview_urls == ["/api/items/review-item/preview/0"]


@pytest.mark.parametrize(
    "approval_status",
    [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED],
)
def test_non_review_preview_urls_stay_remote(
    engine: Engine,
    approval_status: ApprovalStatus,
) -> None:
    with Session(engine) as session:
        item = make_item("decided-item", approval_status=approval_status)
        session.add(item)
        session.add(make_attachment(item.id))
        session.commit()

        summary = ItemSummary.from_db(item, session)

    assert summary.preview_urls == ["https://example.com/preview.jpg"]


def test_preview_endpoint_fetches_and_reuses_cache(
    monkeypatch: pytest.MonkeyPatch,
    preview_cache_dir: Path,
    engine: Engine,
) -> None:
    monkeypatch.setattr(
        "upvote_monitor.api.items.get_preview_urls",
        lambda _session, _item_id: ["https://example.com/preview.jpg"],
    )
    calls = 0

    def fake_get(url: str, *, stream: bool, timeout: int) -> FakeResponse:
        nonlocal calls
        calls += 1
        assert url == "https://example.com/preview.jpg"
        assert stream is True
        assert timeout > 0
        return FakeResponse(b"image-data", "image/jpeg")

    monkeypatch.setattr(preview_cache.requests, "get", fake_get)

    with Session(engine) as session:
        session.add(make_item("cache-item"))
        session.commit()

        response = get_item_preview("cache-item", 0, session)
        second_response = get_item_preview("cache-item", 0, session)

    assert calls == 1
    assert response.media_type == "image/jpeg"
    assert Path(response.path).read_bytes() == b"image-data"
    assert Path(second_response.path) == Path(response.path)
    assert Path(response.path).is_relative_to(preview_cache_dir)


def test_preview_endpoint_rejects_invalid_index(
    monkeypatch: pytest.MonkeyPatch,
    preview_cache_dir: Path,
    engine: Engine,
) -> None:
    monkeypatch.setattr(
        "upvote_monitor.api.items.get_preview_urls",
        lambda _session, _item_id: ["https://example.com/preview.jpg"],
    )

    with Session(engine) as session:
        session.add(make_item("invalid-index"))
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            get_item_preview("invalid-index", 1, session)

    assert exc_info.value.status_code == 404
    assert not any(path.is_file() for path in preview_cache_dir.rglob("*"))


def test_preview_endpoint_rejects_non_image_response(
    monkeypatch: pytest.MonkeyPatch,
    preview_cache_dir: Path,
    engine: Engine,
) -> None:
    monkeypatch.setattr(
        "upvote_monitor.api.items.get_preview_urls",
        lambda _session, _item_id: ["https://example.com/preview.jpg"],
    )
    monkeypatch.setattr(
        preview_cache.requests,
        "get",
        lambda *_args, **_kwargs: FakeResponse(b"<html>", "text/html"),
    )

    with Session(engine) as session:
        session.add(make_item("non-image"))
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            get_item_preview("non-image", 0, session)

    assert exc_info.value.status_code == 502
    assert not any(path.is_file() for path in preview_cache_dir.rglob("*"))


def test_preview_endpoint_removes_partial_oversized_downloads(
    monkeypatch: pytest.MonkeyPatch,
    preview_cache_dir: Path,
    engine: Engine,
) -> None:
    monkeypatch.setattr(preview_cache, "MAX_PREVIEW_BYTES", 4)
    monkeypatch.setattr(
        "upvote_monitor.api.items.get_preview_urls",
        lambda _session, _item_id: ["https://example.com/preview.png"],
    )
    monkeypatch.setattr(
        preview_cache.requests,
        "get",
        lambda *_args, **_kwargs: FakeResponse(b"12345", "image/png"),
    )

    with Session(engine) as session:
        session.add(make_item("oversized"))
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            get_item_preview("oversized", 0, session)

    assert exc_info.value.status_code == 502
    assert not any(path.is_file() for path in preview_cache_dir.rglob("*"))


def test_approve_and_reject_delete_preview_cache(
    preview_cache_dir: Path,
    engine: Engine,
) -> None:
    with Session(engine) as session:
        for item_id in ("approve-cache", "reject-cache"):
            session.add(make_item(item_id))
            _write_cached_preview(item_id)
        session.commit()

        approve_item("approve-cache", BackgroundTasks(), session)
        reject_item("reject-cache", session)

    assert not (preview_cache_dir / "approve-cache").exists()
    assert not (preview_cache_dir / "reject-cache").exists()


def test_recompute_deletes_preview_cache_for_items_moved_out_of_review(
    preview_cache_dir: Path,
    engine: Engine,
) -> None:
    with Session(engine) as session:
        _add_settings(session)
        session.add(
            SourceRule(
                source="reddit",
                rule_type=ListType.BLACKLIST,
                target_type=RuleTargetType.COMMUNITY,
                target_value="python",
                target_label="r/python",
            ),
        )
        session.add(make_item("blacklisted-cache"))
        _write_cached_preview("blacklisted-cache")
        session.commit()

        result = recompute_pending_items_for_rule(
            session,
            "reddit",
            RuleTargetType.COMMUNITY,
            "python",
        )

    assert result.rejected == 1
    assert not (preview_cache_dir / "blacklisted-cache").exists()


def test_cleanup_stale_preview_cache_preserves_only_under_review_items(
    preview_cache_dir: Path,
    engine: Engine,
) -> None:
    with Session(engine) as session:
        session.add(make_item("keep-cache"))
        session.add(
            make_item(
                "remove-cache",
                approval_status=ApprovalStatus.APPROVED,
                download_status=DownloadStatus.COMPLETED,
            ),
        )
        session.commit()

        for item_id in ("keep-cache", "remove-cache", "missing-cache"):
            _write_cached_preview(item_id)

        preview_cache.cleanup_stale_preview_cache(session)

    assert (preview_cache_dir / "keep-cache").exists()
    assert not (preview_cache_dir / "remove-cache").exists()
    assert not (preview_cache_dir / "missing-cache").exists()
