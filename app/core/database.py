"""
Database configuration and session management module.

This file intentionally re-exports singletons from `app.core.database_singleton`
so that unit tests that `sys.modules.pop("app.core.database", None)` do not
accidentally re-initialize a new SQLAlchemy Base/engine on re-import.
"""

from __future__ import annotations

from app.core.database_singleton import (
    AsyncSessionLocal,
    Base,
    SessionLocal,
    engine,
    get_async_db,
    get_async_engine,
    get_async_session_factory,
    get_db,
    to_async_database_url,
)

__all__ = [
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
    "AsyncSessionLocal",
    "get_async_db",
    "get_async_engine",
    "get_async_session_factory",
    "to_async_database_url",
]
