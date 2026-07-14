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


import contextlib
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
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
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

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
