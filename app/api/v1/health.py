"""
Health check endpoints.

Provides system health status check interfaces for frontend and developer tools monitoring.
"""


import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Response

from app.api.schemas.health import HealthResponse, ReadyResponse
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.health_checks import check_database, check_minio, check_redis, check_vector

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
_READY_CACHE_TTL_SEC = max(0.0, float(getattr(settings, "READY_CACHE_TTL_SEC", 2.0) or 2.0))
_ready_cache: dict[str, object] = {"ts": 0.0, "payload": None, "status": 200, "key": None}
_redis_client = None


class _MilvusStoreProxy:
    # Keep /health import-time lightweight; import the real client only when called.
    def get_collection_count(self) -> int:
        from app.storage.vector.milvus import milvus_store

        return milvus_store.get_collection_count()


class _MinioServiceProxy:
    # Keep /health import-time lightweight; import the real client only when called.
    def health_check(self) -> dict[str, Any]:
        from app.storage.object.minio import minio_service

        return minio_service.health_check()


# Backward compatible symbols (tests / tooling patch these).
milvus_store = _MilvusStoreProxy()
minio_service = _MinioServiceProxy()


def _ready_cache_key() -> tuple[object, ...]:
    return (
        (getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").lower(),
        bool(getattr(settings, "TASK_QUEUE_ENABLED", False)),
        bool(getattr(settings, "EMBEDDING_CACHE_ENABLED", False)),
        bool(getattr(settings, "MINIO_ENABLED", False)),
        bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_REQUIRED_FOR_READY", False)),
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


@router.get("/health", response_model=HealthResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def health() -> dict:
    """
    Lightweight health check for web/dev tooling.
    """
    now = datetime.now(UTC).isoformat()
    return {
        "ok": True,
        "time": now,
        "vector_backend": settings.VECTOR_BACKEND,
        "use_langgraph_pipeline": bool(getattr(settings, "USE_LANGGRAPH_PIPELINE", False)),
    }


@router.get("/health/ready", response_model=ReadyResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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

    ok = True

    db_status, db_ok = check_database(SessionLocal)
    ok &= db_ok

    vector_backend = (getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").lower()
    milvus_get_count = milvus_store.get_collection_count if vector_backend == "milvus" else None
    vector_status, _milvus_status, vector_ok = check_vector(
        settings,
        mode="ready",
        milvus_get_collection_count=milvus_get_count,
    )
    ok &= vector_ok

    redis_status, redis_ok, reset_client = check_redis(settings, get_client=_get_redis_client)
    ok &= redis_ok
    if reset_client:
        global _redis_client
        _redis_client = None

    minio_health_check = minio_service.health_check if bool(getattr(settings, "MINIO_ENABLED", False)) else None
    minio_status, minio_ok = check_minio(settings, mode="ready", minio_health_check=minio_health_check)
    ok &= minio_ok

    dify_external_status = None
    if bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", False)):
        try:
            from app.api.v1.integrations_dify import (
                dify_external_knowledge_warmup_ready,
                get_dify_external_knowledge_warmup_status,
            )

            dify_external_status = get_dify_external_knowledge_warmup_status()
            warmup_required = bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_REQUIRED_FOR_READY", False))
            warmup_ready = dify_external_knowledge_warmup_ready()
            dify_external_status["ready"] = warmup_ready
            dify_external_status["required_for_ready"] = warmup_required
            if warmup_required:
                ok &= warmup_ready
        except Exception as exc:  # noqa: BLE001
            dify_external_status = {
                "enabled": True,
                "status": "unknown",
                "ready": False,
                "required_for_ready": bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_REQUIRED_FOR_READY", False)),
                "error": str(exc)[:200],
            }
            if bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_REQUIRED_FOR_READY", False)):
                ok = False

    if not ok:
        response.status_code = 503

    payload = {
        "ok": ok,
        "database": db_status,
        "vector": vector_status,
        "redis": redis_status,
        "minio": minio_status,
        "dify_external_knowledge": dify_external_status,
    }
    _ready_cache["ts"] = time.monotonic()
    _ready_cache["payload"] = payload
    _ready_cache["status"] = response.status_code
    _ready_cache["key"] = cache_key
    return payload
