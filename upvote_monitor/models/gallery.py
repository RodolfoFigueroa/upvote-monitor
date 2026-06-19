from upvote_monitor.models.strict import StrictBaseModel


class GalleryItem(StrictBaseModel):
    caption: str | None = None
    media_id: str
    is_deleted: bool
    id: int


class GalleryData(StrictBaseModel):
    items: list[GalleryItem]
