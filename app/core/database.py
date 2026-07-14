"""
Database configuration and session management module.

This file intentionally re-exports singletons from `app.core.database_singleton`
so that unit tests that `sys.modules.pop("app.core.database", None)` do not
accidentally re-initialize a new SQLAlchemy Base/engine on re-import.
"""


from app.core.database_singleton import (
    Base,
    SessionLocal,
    engine,
    get_db,
)

__all__ = [
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
]
