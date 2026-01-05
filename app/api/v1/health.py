"""
健康检查端点

提供系统健康状态检查接口，用于前端和开发工具监控。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Response

from app.core.config import settings
from app.core.database import SessionLocal
from app.storage.vector.milvus import milvus_store


router = APIRouter()


@router.get("/health")
def health() -> dict:
    """
    Lightweight health check for web/dev tooling.
    """
    now = datetime.now(timezone.utc).isoformat()
    return {
        "ok": True,
        "time": now,
        "vector_backend": settings.VECTOR_BACKEND,
        "use_langgraph_pipeline": bool(getattr(settings, "USE_LANGGRAPH_PIPELINE", False)),
    }


@router.get("/health/ready")
def ready(response: Response) -> dict:
    """
    Readiness probe for orchestration (k8s, compose, etc).

    - Returns 200 when required deps are reachable
    - Returns 503 when one or more deps are down
    """
    from sqlalchemy import text

    ok = True

    db_status = {"status": "disconnected"}
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        db_status["status"] = "connected"
    except Exception as exc:  # noqa: BLE001
        ok = False
        db_status["error"] = str(exc)[:200]
    finally:
        db.close()

    vector_backend = (getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").lower()
    vector_status: dict = {"backend": vector_backend, "status": "unknown"}
    if vector_backend == "milvus":
        try:
            milvus_store.get_collection_count()
            vector_status["status"] = "connected"
        except Exception as exc:  # noqa: BLE001
            ok = False
            vector_status["status"] = "disconnected"
            vector_status["error"] = str(exc)[:200]
    else:
        vector_status["status"] = "ready"

    redis_required = bool(getattr(settings, "TASK_QUEUE_ENABLED", False))
    redis_optional_cache = bool(getattr(settings, "EMBEDDING_CACHE_ENABLED", False))
    redis_enabled = redis_required or redis_optional_cache
    redis_status = {
        "status": "disabled",
        "enabled": redis_enabled,
        "required": redis_required,
        "embedding_cache_enabled": redis_optional_cache,
    }
    if redis_enabled:
        try:
            import redis

            r = redis.Redis.from_url(
                settings.REDIS_URL,
                socket_timeout=1,
                socket_connect_timeout=1,
                decode_responses=True,
            )
            r.ping()
            redis_status["status"] = "connected"
        except Exception as exc:  # noqa: BLE001
            redis_status["status"] = "disconnected"
            redis_status["error"] = str(exc)[:200]
            # Redis is only required when the task queue is enabled.
            if redis_required:
                ok = False

    if not ok:
        response.status_code = 503

    return {
        "ok": ok,
        "database": db_status,
        "vector": vector_status,
        "redis": redis_status,
    }
