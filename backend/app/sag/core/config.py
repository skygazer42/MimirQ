"""
Adapter to reuse the project's configuration inside SAG code.
"""
from app.core.config import settings


def get_settings():
    """Expose existing FastAPI settings to SAG modules."""
    return settings

