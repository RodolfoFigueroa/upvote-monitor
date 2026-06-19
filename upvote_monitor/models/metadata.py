from abc import ABC
from typing import Annotated, Literal

from pydantic import Field, computed_field

from upvote_monitor.models.image import AnimatedImage, Image
from upvote_monitor.models.preview import best_image_list_url
from upvote_monitor.models.strict import StrictBaseModel
from upvote_monitor.models.url import UnescapedUrl


class _BaseMediaMetadata(StrictBaseModel, ABC):
    status: Literal["valid"]
    id: str
    o: list[Image] | None = None
    p: list[Image]
    s: Image | AnimatedImage

    @computed_field
    @property
    def download_url(self) -> UnescapedUrl:
        return self.s.download_url


class ImageMediaMetadata(_BaseMediaMetadata):
    e: Literal["Image"]
    m: Literal["image/jpg", "image/png"]
    s: Image


class AnimatedImageMediaMetadata(_BaseMediaMetadata):
    e: Literal["AnimatedImage"]
    m: Literal["image/gif"]
    s: AnimatedImage


MediaMetadata = Annotated[
    ImageMediaMetadata | AnimatedImageMediaMetadata, Field(discriminator="e")
]


def best_metadata_preview_url(
    metadata: MediaMetadata, max_width: int = 640
) -> UnescapedUrl:
    if metadata.p:
        return best_image_list_url(metadata.p, max_width=max_width)
    return metadata.s.download_url
