from upvote_monitor.models.image import VariantImage
from upvote_monitor.models.strict import StrictBaseModel


class Variants(StrictBaseModel):
    obfuscated: VariantImage | None = None
    nsfw: VariantImage | None = None
    gif: VariantImage | None = None
    mp4: VariantImage | None = None
