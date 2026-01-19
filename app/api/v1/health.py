"""
Health check endpoints.

Provides system health status check interfaces for frontend and developer tools monitoring.
"""


from datetime import datetime, timezone
import time

from fastapi import APIRouter, Response

from app.core.config import settings
from app.core.database import SessionLocal
from app.storage.vector.milvus import milvus_store
from app.storage.object.minio import minio_service
from app.api.schemas.health import HealthResponse, ReadyResponse


router = APIRouter()
_READY_CACHE_TTL_SEC = 2.0
_ready_cache: dict[str, object] = {"ts": 0.0, "payload": None, "status": 200, "key": None}
_redis_client = None


def _ready_cache_key() -> tuple[object, ...]:
    return (
        (getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").lower(),
        bool(getattr(settings, "TASK_QUEUE_ENABLED", False)),
        bool(getattr(settings, "EMBEDDING_CACHE_ENABLED", False)),
        bool(getattr(settings, "MINIO_ENABLED", False)),
        # Include endpoints so the cache doesn't hide hot-reloaded settings changes.
        str(getattr(settings, "REDIS_URL", "") or ""),
        str(getattr(settings, "MILVUS_HOST", "") or ""),
        int(getattr(settings, "MILVUS_PORT", 0) or 0),
        str(getattr(settings, "MINIO_ENDPOINT", "") or ""),
    )


def _get_ready_cache(cache_key: tuple[object, ...]):
    now = time.monotonic()
    payload = _ready_cache.get("payload")
    if (
        payload is not None
        and _ready_cache.get("key") == cache_key
        and (now - float(_ready_cache.get("ts") or 0.0)) < _READY_CACHE_TTL_SEC
    ):
        return payload, int(_ready_cache.get("status") or 200)
    return None, None


def _get_redis_client():
    global _redis_client
    if _redis_client is None:
        import redis

        _redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_timeout=1,
            socket_connect_timeout=1,
            decode_responses=True,
        )
    return _redis_client


@router.get("/health", response_model=HealthResponse)
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


@router.get("/health/ready", response_model=ReadyResponse)
def ready(response: Response) -> dict:
    """
    Readiness probe for orchestration (k8s, compose, etc).

    - Returns 200 when required deps are reachable
    - Returns 503 when one or more deps are down
    """
    cache_key = _ready_cache_key()
    cached_payload, cached_status = _get_ready_cache(cache_key)
    if cached_payload is not None:
        response.status_code = cached_status
        return cached_payload

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
            client = _get_redis_client()
            client.ping()
            redis_status["status"] = "connected"
        except Exception as exc:  # noqa: BLE001
            global _redis_client
            _redis_client = None
            redis_status["status"] = "disconnected"
            redis_status["error"] = str(exc)[:200]
            # Redis is only required when the task queue is enabled.
            if redis_required:
                ok = False

    minio_enabled = bool(getattr(settings, "MINIO_ENABLED", False))
    minio_status = {"status": "disabled", "enabled": minio_enabled}
    if minio_enabled:
        minio_status = minio_service.health_check()
        if minio_status.get("status") != "connected":
            ok = False

    if not ok:
        response.status_code = 503

    payload = {
        "ok": ok,
        "database": db_status,
        "vector": vector_status,
        "redis": redis_status,
        "minio": minio_status,
    }
    _ready_cache["ts"] = time.monotonic()
    _ready_cache["payload"] = payload
    _ready_cache["status"] = response.status_code
    _ready_cache["key"] = cache_key
    return payload
