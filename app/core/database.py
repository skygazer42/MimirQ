"""Database engine, ORM base and request-scoped Session ownership."""

import contextlib
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import settings


def _build_engine_kwargs(url: str) -> dict[str, bool | int]:
    parsed_url = make_url(url)
    engine_kwargs: dict[str, bool | int] = {"pool_pre_ping": settings.DB_POOL_PRE_PING}
    if not parsed_url.drivername.startswith("sqlite"):
        engine_kwargs.update(
            {
                "pool_size": settings.DB_POOL_SIZE,
                "max_overflow": settings.DB_MAX_OVERFLOW,
                "pool_timeout": settings.DB_POOL_TIMEOUT_SEC,
                "pool_recycle": settings.DB_POOL_RECYCLE_SEC,
            }
        )
    return engine_kwargs


_engine_kwargs = _build_engine_kwargs(settings.DATABASE_URL)
engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
Base = declarative_base()


def get_db() -> Iterator[Session]:
    """Yield a request Session, then return its connection to the pool."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
        raise
    finally:
        db.close()


__all__ = ["Base", "SessionLocal", "engine", "get_db"]
