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

from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# Create database engine (singleton per interpreter).
_db_url = make_url(settings.DATABASE_URL)
_engine_kwargs = {"pool_pre_ping": bool(getattr(settings, "DB_POOL_PRE_PING", True))}

if not (_db_url.drivername or "").startswith("sqlite"):
    _engine_kwargs.update(
        {
            "pool_size": int(getattr(settings, "DB_POOL_SIZE", 10)),
            "max_overflow": int(getattr(settings, "DB_MAX_OVERFLOW", 20)),
            "pool_timeout": int(getattr(settings, "DB_POOL_TIMEOUT_SEC", 30)),
            "pool_recycle": int(getattr(settings, "DB_POOL_RECYCLE_SEC", 1800)),
        }
    )

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)

# Session factory.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ORM Base.
Base = declarative_base()


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

