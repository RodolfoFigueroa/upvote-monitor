from typing import Annotated, Literal

from pydantic import Field

from upvote_monitor.models.strict import StrictBaseModel
from upvote_monitor.models.url import UnescapedUrl


class _BaseMedia(StrictBaseModel):
    pass


class OEmbed(StrictBaseModel):
    author_name: str | None = None
    author_url: UnescapedUrl | None = None
    provider_url: UnescapedUrl
    version: int
    title: str
    thumbnail_width: int
    height: int
    width: int
    html: str
    provider_name: str
    thumbnail_url: UnescapedUrl
    type: Literal["video"]
    thumbnail_height: int


class _BaseOtherMedia(_BaseMedia):
    type: str
    oembed: OEmbed


class OtherMediaYoutube(_BaseOtherMedia):
    type: Literal["youtube.com"]


class OtherMediaRedGIFs(_BaseOtherMedia):
    type: Literal["redgifs.com"]


OtherMedia = Annotated[
    OtherMediaYoutube | OtherMediaRedGIFs,
    Field(discriminator="type"),
]


class RedditVideo(StrictBaseModel):
    bitrate_kbps: int
    fallback_url: UnescapedUrl
    has_audio: bool
    height: int
    width: int
    scrubber_media_url: UnescapedUrl
    dash_url: UnescapedUrl
    duration: int
    hls_url: UnescapedUrl
    is_gif: bool
    transcoding_status: Literal["completed"]


class RedditMedia(_BaseMedia):
    reddit_video: RedditVideo
