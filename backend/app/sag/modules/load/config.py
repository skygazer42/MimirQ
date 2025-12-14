from app.sag.models.base import SAGBaseModel


class LoadBaseConfig(SAGBaseModel):
    """Placeholder for compatibility."""
    path: str | None = None


class LoadResult(SAGBaseModel):
    """Placeholder result."""
    success: bool = True

