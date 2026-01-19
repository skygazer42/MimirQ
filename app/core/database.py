"""
Database configuration and session management module

Provides database connection, session factory, and dependency injection.
"""
import contextlib

from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# Create database engine
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

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ORM Base
Base = declarative_base()


def get_db():
    """Dependency: yield a DB session"""
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
