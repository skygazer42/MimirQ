"""
Backward compatibility shim. Please import from app.core.database instead.
"""
from app.core.database import Base, engine, SessionLocal, get_db  # noqa: F401
