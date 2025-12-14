from pydantic import BaseModel
from pydantic import ConfigDict


class SAGBaseModel(BaseModel):
    """BaseModel with orm_mode enabled for compatibility."""

    model_config = ConfigDict(from_attributes=True)
