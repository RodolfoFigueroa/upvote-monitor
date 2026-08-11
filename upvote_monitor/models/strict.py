from pydantic import BaseModel, ConfigDict


class StrictBaseModel(BaseModel):
    """Validate consumed Reddit fields while tolerating upstream additions."""

    model_config = ConfigDict(extra="ignore")
