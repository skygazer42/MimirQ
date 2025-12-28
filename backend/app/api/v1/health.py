"""
Health check endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.config import settings


router = APIRouter()


@router.get("/health")
def health() -> dict:
    """
    Lightweight health check for frontend/dev tooling.
    """
    now = datetime.now(timezone.utc).isoformat()
    return {
        "ok": True,
        "time": now,
        "vector_backend": settings.VECTOR_BACKEND,
        "use_langgraph_pipeline": bool(getattr(settings, "USE_LANGGRAPH_PIPELINE", False)),
    }

