from abc import ABC, abstractmethod

from pydantic import computed_field

from upvote_monitor.models.strict import StrictBaseModel
from upvote_monitor.models.url import UnescapedUrl


class _BaseImage(StrictBaseModel, ABC):
    x: int
    y: int

    @computed_field
    @property
    @abstractmethod
    def download_url(self) -> UnescapedUrl: ...


class Image(_BaseImage):
    u: UnescapedUrl

    @computed_field
    @property
    def download_url(self) -> UnescapedUrl:
        return self.u


class AnimatedImage(_BaseImage):
    gif: UnescapedUrl
    mp4: UnescapedUrl

    @computed_field
    @property
    def download_url(self) -> UnescapedUrl:
        return self.mp4


class SourceImage(StrictBaseModel):
    url: UnescapedUrl
    width: int
    height: int


class VariantImage(StrictBaseModel):
    source: SourceImage
    resolutions: list[SourceImage]
