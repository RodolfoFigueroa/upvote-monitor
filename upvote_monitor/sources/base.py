from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from upvote_monitor.enums import DownloadStrategy


@dataclass(frozen=True)
class MediaAttachmentInput:
    sort_index: int
    media_type: str
    download_url: str
    preview_url: str | None = None
    content_type: str | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    extension: str | None = None
    download_strategy: DownloadStrategy = DownloadStrategy.HTTP


@dataclass(frozen=True)
class SourceItem:
    source: str
    source_item_id: str
    title: str
    author_name: str | None
    author_label: str | None
    community_name: str | None
    community_label: str | None
    item_kind: str
    source_url: str
    created_at: datetime
    raw_data: dict[str, Any]
    media: list[MediaAttachmentInput]


class SourceProvider(Protocol):
    source: str

    def iter_liked_items(self) -> Iterable[SourceItem]: ...
