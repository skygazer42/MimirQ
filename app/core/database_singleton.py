"""
Database singletons (engine / sessionmaker / declarative Base).

Why this module exists:
- Some unit tests intentionally `sys.modules.pop("app.core.database", None)` to
  assert that unrelated modules do not eagerly import the database layer.
- If `app.core.database` is later imported again, its top-level module code would
  normally re-run and create a *new* SQLAlchemy `Base` and engine, which breaks
  model registration and contract tests that assert tables are present in
  `Base.metadata`.

Keeping the singletons in a separate module prevents accidental re-initialization
when `app.core.database` is removed from `sys.modules`.
"""

from __future__ import annotations

import contextlib
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

def _build_engine_kwargs(url: str) -> dict[str, Any]:
    parsed_url = make_url(url)
    engine_kwargs: dict[str, Any] = {"pool_pre_ping": bool(getattr(settings, "DB_POOL_PRE_PING", True))}
    if not (parsed_url.drivername or "").startswith("sqlite"):
        engine_kwargs.update(
            {
                "pool_size": int(getattr(settings, "DB_POOL_SIZE", 10)),
                "max_overflow": int(getattr(settings, "DB_MAX_OVERFLOW", 20)),
                "pool_timeout": int(getattr(settings, "DB_POOL_TIMEOUT_SEC", 30)),
                "pool_recycle": int(getattr(settings, "DB_POOL_RECYCLE_SEC", 1800)),
            }
        )
    return engine_kwargs


_engine_kwargs = _build_engine_kwargs(settings.DATABASE_URL)

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)

# Session factory.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ORM Base.
Base = declarative_base()

# Async engine/session are created lazily to avoid import-time failures when async
# DB drivers are not installed in sync-only environments.
_async_engine = None
AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def to_async_database_url(sync_database_url: str) -> str:
    """Convert a sync SQLAlchemy URL into an async-driver URL."""
    parsed = make_url(sync_database_url)
    drivername = parsed.drivername or ""
    if "+asyncpg" in drivername or "+aiosqlite" in drivername:
        return parsed.render_as_string(hide_password=False)
    if drivername.startswith("postgresql") or drivername == "postgres":
        parsed = parsed.set(drivername="postgresql+asyncpg")
        return parsed.render_as_string(hide_password=False)
    if drivername.startswith("sqlite"):
        parsed = parsed.set(drivername="sqlite+aiosqlite")
        return parsed.render_as_string(hide_password=False)
    return parsed.render_as_string(hide_password=False)


def get_async_engine():  # noqa: ANN201
    global _async_engine
    if _async_engine is None:
        async_url = to_async_database_url(settings.DATABASE_URL)
        _async_engine = create_async_engine(async_url, **_build_engine_kwargs(async_url))
    return _async_engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    global AsyncSessionLocal
    if AsyncSessionLocal is None:
        AsyncSessionLocal = async_sessionmaker(
            bind=get_async_engine(),
            autocommit=False,
            autoflush=False,
        )
    return AsyncSessionLocal


async def get_async_db():  # noqa: ANN201
    """FastAPI dependency: yield an async DB session."""
    db = get_async_session_factory()()
    try:
        yield db
    except Exception:
        with contextlib.suppress(Exception):
            await db.rollback()
        raise
    finally:
        await db.close()


def get_db():  # noqa: ANN201
    """FastAPI dependency: yield a DB session."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        # Ensure the connection is returned to the pool in a clean state.
        with contextlib.suppress(Exception):
            db.rollback()
        raise
    finally:
        db.close()
