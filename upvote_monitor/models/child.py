import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, HttpUrl, computed_field, model_validator
from yt_dlp import YoutubeDL

from upvote_monitor.functions import download_image_from_url
from upvote_monitor.models.gallery import GalleryData
from upvote_monitor.models.media import OtherMedia, RedditMedia
from upvote_monitor.models.metadata import MediaMetadata, best_metadata_preview_url
from upvote_monitor.models.preview import Preview, VideoPreview, best_preview_image_url
from upvote_monitor.models.strict import StrictBaseModel
from upvote_monitor.models.url import UnescapedUrl


def _add_post_hint_to_data(child_data: dict) -> None:
    if "post_hint" not in child_data:
        if child_data.get("is_gallery"):
            child_data["post_hint"] = "gallery"
        else:
            media_metadata = child_data.get("media_metadata")
            if media_metadata:
                child_data["post_hint"] = "other"
            else:
                child_data["post_hint"] = "no_media"


def _ordered_gallery_metadata(
    gallery_data: GalleryData | None,
    media_metadata: dict[str, MediaMetadata] | None,
) -> list[MediaMetadata]:
    if media_metadata is None:
        return []

    if gallery_data is None:
        return [
            metadata for metadata in media_metadata.values() if metadata is not None
        ]

    ordered: list[MediaMetadata] = []
    for item in gallery_data.items:
        if item.is_deleted:
            continue
        metadata = media_metadata.get(item.media_id)
        if metadata is not None:
            ordered.append(metadata)
    return ordered


class _BaseChildData(StrictBaseModel, ABC):
    all_awardings: list[dict]
    allow_live_comments: bool
    approved_at_utc: datetime | None
    approved_by: str | None
    archived: bool
    author: str
    author_flair_background_color: str | None
    author_flair_css_class: str | None
    author_flair_richtext: list[dict[str, str]] | None = None
    author_flair_template_id: str | None
    author_flair_text: str | None
    author_flair_text_color: str | None
    author_flair_type: str | None = None
    author_fullname: str | None = None
    author_is_blocked: bool
    author_patreon_flair: bool | None = None
    author_premium: bool | None = None
    awarders: list
    banned_at_utc: datetime | None
    banned_by: str | None
    category: str | None
    can_gild: bool
    can_mod_post: bool
    clicked: bool
    content_categories: list[str] | None
    contest_mode: bool
    created: datetime
    created_utc: datetime
    crosspost_parent: str | None = None
    crosspost_parent_list: list["ChildData"] | None = None
    discussion_type: str | None
    distinguished: str | None
    domain: str
    downs: int
    edited: bool | int
    gallery_data: GalleryData | None = None
    gilded: int
    gildings: dict[str, int]
    hidden: bool
    hide_score: bool
    id: str
    is_created_from_ads_ui: bool
    is_crosspostable: bool
    is_gallery: bool = False
    is_meta: bool
    is_original_content: bool
    is_reddit_media_domain: bool
    is_robot_indexable: bool
    is_self: bool
    is_video: bool
    likes: bool | None
    link_flair_background_color: str | None
    link_flair_css_class: str | None
    link_flair_richtext: list[dict[str, str]]
    link_flair_template_id: str | None = None
    link_flair_text: str | None
    link_flair_text_color: str | None = None
    link_flair_type: str
    locked: bool
    media: None | OtherMedia | RedditMedia
    media_embed: dict | None
    media_only: bool
    mod_note: str | None
    mod_reason_by: str | None
    mod_reason_title: str | None
    mod_reports: list | None
    name: str
    no_follow: bool
    num_comments: int
    num_crossposts: int
    num_reports: int | None
    over_18: bool
    permalink: str
    pinned: bool
    poll_data: dict[str, Any] | bool | None = None
    pwls: int | None
    quarantine: bool
    removal_reason: str | None
    removed_by: str | None
    removed_by_category: str | None
    report_reasons: str | None
    saved: bool
    score: int
    secure_media: dict | None
    secure_media_embed: dict | None
    selftext: str
    selftext_html: str | None
    spoiler: bool
    stickied: bool
    subreddit: str
    subreddit_name_prefixed: str
    subreddit_subscribers: int
    suggested_sort: str | None
    title: str
    thumbnail: str | None = None
    thumbnail_height: int | None = None
    thumbnail_width: int | None = None
    top_awarded_type: str | None
    total_awards_received: int
    treatment_tags: list[str]
    send_replies: bool
    subreddit_type: str
    ups: int
    upvote_ratio: float
    url: UnescapedUrl
    url_overridden_by_dest: HttpUrl | None = None
    user_reports: list
    wls: int | None
    view_count: int | None
    visited: bool
    subreddit_id: str

    @computed_field
    @property
    @abstractmethod
    def media_download_url(self) -> list[UnescapedUrl]: ...

    @computed_field
    @property
    @abstractmethod
    def media_preview_url(self) -> list[UnescapedUrl]: ...

    @abstractmethod
    def _download_to_path(self, url: UnescapedUrl, path: os.PathLike | str) -> None: ...

    def download_to_path(self, path: os.PathLike | str) -> None:
        if len(self.media_download_url) != 1:
            msg = "More than one media download URL detected. Use download_to_dir instead."
            raise ValueError(msg)

        self._download_to_path(self.media_download_url[0], path)

    def download_to_dir(self, dir_path: os.PathLike) -> None:
        dir_path = Path(dir_path)
        dir_path.mkdir(parents=True, exist_ok=True)

        for i, url in enumerate(self.media_download_url):
            fpath = dir_path / f"{i:02d}"
            self._download_to_path(url, fpath)


class _BaseImageChildData(_BaseChildData):
    def _download_to_path(self, url: UnescapedUrl, path: os.PathLike | str) -> None:
        download_image_from_url(url, path)


class _BaseVideoChildData(_BaseChildData):
    def _download_to_path(self, url: UnescapedUrl, path: os.PathLike | str) -> None:
        path = Path(path)
        with YoutubeDL(
            params={"outtmpl": str(path.parent / f"{path.stem}.%(ext)s")}
        ) as ydl:
            ydl.download(str(url))


class ImageChildData(_BaseImageChildData):
    post_hint: Literal["image"]
    preview: Preview
    media: None

    @computed_field
    @property
    def media_download_url(self) -> list[UnescapedUrl]:
        return [self.url]

    @computed_field
    @property
    def media_preview_url(self) -> list[UnescapedUrl]:
        return [best_preview_image_url(self.preview.images[0])]


class OtherChildData(_BaseImageChildData):
    post_hint: Literal["other"]
    media_metadata: dict[str, MediaMetadata]
    media: None

    @computed_field
    @property
    def media_download_url(self) -> list[UnescapedUrl]:
        return [
            media_metadata.download_url
            for media_metadata in self.media_metadata.values()
            if media_metadata is not None
        ]

    @computed_field
    @property
    def media_preview_url(self) -> list[UnescapedUrl]:
        return [
            best_metadata_preview_url(media_metadata)
            for media_metadata in self.media_metadata.values()
            if media_metadata is not None
        ]


class GalleryChildData(_BaseImageChildData):
    post_hint: Literal["gallery"]
    media: None
    media_metadata: dict[str, MediaMetadata] | None
    preview: Preview | None = None

    @computed_field
    @property
    def media_download_url(self) -> list[UnescapedUrl]:
        return [
            metadata.download_url
            for metadata in _ordered_gallery_metadata(
                self.gallery_data, self.media_metadata
            )
        ]

    @computed_field
    @property
    def media_preview_url(self) -> list[UnescapedUrl]:
        return [
            best_metadata_preview_url(metadata)
            for metadata in _ordered_gallery_metadata(
                self.gallery_data, self.media_metadata
            )
        ]

    def _download_to_path(self, url: UnescapedUrl, path: os.PathLike | str) -> None:
        download_image_from_url(url, path)


class RichVideoChildData(_BaseVideoChildData):
    post_hint: Literal["rich:video"]
    preview: VideoPreview
    media: OtherMedia

    @computed_field
    @property
    def media_download_url(self) -> list[UnescapedUrl]:
        return [self.url]

    @computed_field
    @property
    def media_preview_url(self) -> list[UnescapedUrl]:
        if self.media.oembed.thumbnail_url is not None:
            return [self.media.oembed.thumbnail_url]
        if self.preview.images:
            return [best_preview_image_url(self.preview.images[0])]
        if self.preview.reddit_video_preview is not None:
            return [self.preview.reddit_video_preview.fallback_url]
        return []


class HostedVideoChildData(_BaseVideoChildData):
    post_hint: Literal["hosted:video"]
    media: RedditMedia
    preview: Preview

    @computed_field
    @property
    def media_download_url(self) -> list[UnescapedUrl]:
        return [self.media.reddit_video.fallback_url]

    @computed_field
    @property
    def media_preview_url(self) -> list[UnescapedUrl]:
        return [self.media.reddit_video.scrubber_media_url]


class NoMediaChildData(_BaseChildData):
    post_hint: Literal["no_media"]
    media: None

    @computed_field
    @property
    def media_download_url(self) -> list[UnescapedUrl]:
        return []

    @computed_field
    @property
    def media_preview_url(self) -> list[UnescapedUrl]:
        return []

    def _download_to_path(self, url: UnescapedUrl, path: os.PathLike | str) -> None:
        raise NotImplementedError


class LinkChildData(_BaseChildData):
    post_hint: Literal["link"]
    preview: Preview
    media: None

    @computed_field
    @property
    def media_download_url(self) -> list[UnescapedUrl]:
        return [self.preview.images[0].source.url]

    @computed_field
    @property
    def media_preview_url(self) -> list[UnescapedUrl]:
        if not self.preview.images:
            return []
        return [best_preview_image_url(self.preview.images[0])]

    def _download_to_path(self, url: UnescapedUrl, path: os.PathLike | str) -> None:
        raise NotImplementedError


class SelfChildData(_BaseChildData):
    post_hint: Literal["self"]
    preview: Preview
    media: None

    @computed_field
    @property
    def media_download_url(self) -> list[UnescapedUrl]:
        return [self.preview.images[0].source.url]

    @computed_field
    @property
    def media_preview_url(self) -> list[UnescapedUrl]:
        if not self.preview.images:
            return []
        return [best_preview_image_url(self.preview.images[0])]

    def _download_to_path(self, url: UnescapedUrl, path: os.PathLike | str) -> None:
        raise NotImplementedError


ChildData = Annotated[
    ImageChildData
    | RichVideoChildData
    | HostedVideoChildData
    | GalleryChildData
    | OtherChildData
    | LinkChildData
    | SelfChildData
    | NoMediaChildData,
    Field(discriminator="post_hint"),
]


class Children(StrictBaseModel):
    @model_validator(mode="before")
    @classmethod
    def handle_missing_post_hint(cls, input: Any) -> Any:
        child_data = input.get("data")
        if child_data:
            _add_post_hint_to_data(child_data)

        crosspost_parents = child_data.get("crosspost_parent_list")
        if crosspost_parents:
            for parent in crosspost_parents:
                _add_post_hint_to_data(parent)
        return input

    kind: Literal["t3"]
    data: ChildData
