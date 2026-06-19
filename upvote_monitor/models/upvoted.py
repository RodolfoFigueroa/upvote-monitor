from typing import Literal

from upvote_monitor.models.child import Children
from upvote_monitor.models.strict import StrictBaseModel


class UpvotedData(StrictBaseModel):
    after: str | None
    dist: int
    modhash: str
    geo_filter: str
    children: list[Children]
    before: str | None


class UpvotedResponse(StrictBaseModel):
    kind: Literal["Listing"]
    data: UpvotedData
