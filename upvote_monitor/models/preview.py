from typing import Literal

from pydantic import HttpUrl

from upvote_monitor.models.image import Image, SourceImage
from upvote_monitor.models.strict import StrictBaseModel
from upvote_monitor.models.url import UnescapedUrl
from upvote_monitor.models.variant import Variants


def best_source_image_url(
    images: list[SourceImage],
    *,
    fallback: UnescapedUrl,
    max_width: int = 640,
) -> UnescapedUrl:
    if not images:
        return fallback

    within_max = [img for img in images if img.width <= max_width]
    if within_max:
        return max(within_max, key=lambda img: img.width).url
    return max(images, key=lambda img: img.width).url


def best_image_list_url(images: list[Image], max_width: int = 640) -> UnescapedUrl:
    if not images:
        msg = "images must not be empty"
        raise ValueError(msg)

    within_max = [img for img in images if img.x <= max_width]
    if within_max:
        return max(within_max, key=lambda img: img.x).u
    return max(images, key=lambda img: img.x).u


class PreviewImage(StrictBaseModel):
    source: SourceImage
    resolutions: list[SourceImage]
    variants: Variants | StrictBaseModel
    id: str


def best_preview_image_url(
    preview_image: PreviewImage,
    max_width: int = 640,
) -> UnescapedUrl:
    return best_source_image_url(
        preview_image.resolutions,
        fallback=preview_image.source.url,
        max_width=max_width,
    )


class RedditVideoPreview(StrictBaseModel):
    bitrate_kbps: int
    fallback_url: HttpUrl
    has_audio: bool
    height: int
    width: int
    scrubber_media_url: HttpUrl
    dash_url: HttpUrl
    duration: int
    hls_url: HttpUrl
    is_gif: bool
    transcoding_status: Literal["completed"]


class Preview(StrictBaseModel):
    images: list[PreviewImage]
    enabled: bool


class VideoPreview(Preview):
    reddit_video_preview: RedditVideoPreview | None = None
