"""
Health check endpoints.

Public endpoints stay probe-friendly and minimal; detailed dependency state is admin-gated.
"""

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, TypedDict
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.health import HealthDetailsResponse, HealthResponse, ReadyResponse
from app.api.utils.http_exception_responses import (
    DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.health_checks import check_database, check_minio, check_redis, check_vector
from app.core.redis_client import LazyRedisClient
from app.services.rag_runtime_warmup import (
    get_rag_runtime_warmup_status,
    rag_runtime_warmup_ready,
)
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission
from app.tasks.queue import is_queue_initialized


class _ReadyCache(TypedDict):
    ts: float
    payload: dict[str, Any] | None
    status: int
    key: tuple[object, ...] | None


router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
_READY_CACHE_TTL_SEC = max(0.0, settings.READY_CACHE_TTL_SEC or 2.0)
_ready_cache: _ReadyCache = {"ts": 0.0, "payload": None, "status": 200, "key": None}
_redis_client_slot = LazyRedisClient(
    url=lambda: settings.REDIS_URL,
    kwargs={
        "socket_timeout": 1,
        "socket_connect_timeout": 1,
        "decode_responses": True,
    },
    suppress_errors=False,
)
_get_redis_client = _redis_client_slot.get


def invalidate_ready_cache() -> None:
    _ready_cache.update({"ts": 0.0, "payload": None, "status": 200, "key": None})


class _MilvusStoreProxy:
    # Keep /health import-time lightweight; import the real client only when called.
    def get_collection_count(self) -> int:
        from app.storage.vector.milvus import milvus_store

        return milvus_store.get_collection_count()


class _MinioServiceProxy:
    # Keep /health import-time lightweight; import the real client only when called.
    def is_enabled(self) -> bool:
        from app.storage.object.runtime import document_object_storage_enabled

        return settings.MINIO_ENABLED or document_object_storage_enabled()

    def health_check(self) -> dict[str, Any]:
        from app.storage.object.runtime import get_document_object_store

        store = get_document_object_store()
        if store is not None:
            return store.health_check()
        from app.storage.object.minio import minio_service

        return minio_service.health_check()


# Backward compatible symbols (tests / tooling patch these).
milvus_store = _MilvusStoreProxy()
minio_service = _MinioServiceProxy()


def _ensure_admin(db: Session, tenant_id: UUID, account_id: str) -> None:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.OBSERVABILITY_READ,
        detail="No permission to access observability dashboards",
    )


def _ready_cache_key() -> tuple[object, ...]:
    return (
        (settings.VECTOR_BACKEND or "milvus").lower(),
        settings.TASK_QUEUE_ENABLED,
        settings.DB_CREATE_ALL_ON_STARTUP,
        settings.DB_RUNTIME_MIGRATIONS_ENABLED,
        settings.EMBEDDING_CACHE_ENABLED,
        settings.MINIO_ENABLED,
        settings.OBJECT_STORAGE_ENABLED,
        settings.OBJECT_STORAGE_DOCUMENTS_ENABLED,
        settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_REQUIRED_FOR_READY,
        settings.RAG_RUNTIME_WARMUP_ENABLED,
        settings.RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY,
        # Include endpoints so the cache doesn't hide hot-reloaded settings changes.
        settings.REDIS_URL or "",
        settings.MILVUS_HOST or "",
        settings.MILVUS_PORT or 0,
        settings.MINIO_ENDPOINT or "",
        settings.OBJECT_STORAGE_PROVIDER or "",
        settings.OBJECT_STORAGE_ENDPOINT or "",
        settings.OBJECT_STORAGE_BUCKET_NAME or "",
        settings.DATA_REGION or "",
        settings.OBJECT_STORAGE_REGION_PROFILES or "",
    )


def _get_ready_cache(cache_key: tuple[object, ...]) -> tuple[dict[str, Any], int] | None:
    now = time.monotonic()
    payload = _ready_cache["payload"]
    if payload is not None and _ready_cache["key"] == cache_key and (now - _ready_cache["ts"]) < _READY_CACHE_TTL_SEC:
        return payload, _ready_cache["status"]
    return None


def _collect_ready_details() -> tuple[dict[str, Any], int, dict[str, Any] | None]:
    cache_key = _ready_cache_key()
    cached = _get_ready_cache(cache_key)
    if cached is not None:
        cached_payload, cached_status = cached
        return cached_payload, cached_status, cached_payload.get("milvus")

    ok = True

    application_manages_schema = settings.DB_CREATE_ALL_ON_STARTUP or settings.DB_RUNTIME_MIGRATIONS_ENABLED
    db_status, db_ok = check_database(SessionLocal, require_schema_current=not application_manages_schema)
    ok &= db_ok

    vector_backend = (settings.VECTOR_BACKEND or "milvus").lower()
    milvus_get_count = milvus_store.get_collection_count if vector_backend == "milvus" else None
    vector_status, milvus_status, vector_ok = check_vector(
        settings,
        mode="ready",
        milvus_get_collection_count=milvus_get_count,
    )
    ok &= vector_ok

    redis_status, redis_ok, reset_client = check_redis(settings, get_client=_get_redis_client)
    ok &= redis_ok
    if reset_client:
        _redis_client_slot.invalidate()

    object_storage_ready_probe_enabled = minio_service.is_enabled()
    minio_health_check = minio_service.health_check if object_storage_ready_probe_enabled else None
    minio_status, minio_ok = check_minio(
        settings,
        mode="ready",
        minio_health_check=minio_health_check,
        enabled_override=object_storage_ready_probe_enabled,
    )
    ok &= minio_ok

    rag_runtime_warmup_status = get_rag_runtime_warmup_status()
    rag_runtime_warmup_status["required_for_ready"] = settings.RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY
    if settings.RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY:
        ok &= rag_runtime_warmup_ready()

    dify_external_status = None
    if settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED:
        try:
            from app.api.v1.integrations_dify import (
                dify_external_knowledge_warmup_ready,
                get_dify_external_knowledge_warmup_status,
            )

            dify_external_status = get_dify_external_knowledge_warmup_status()
            warmup_required = settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_REQUIRED_FOR_READY
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
                "required_for_ready": settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_REQUIRED_FOR_READY,
                "error": str(exc)[:200],
            }
            if settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_REQUIRED_FOR_READY:
                ok = False

    payload = {
        "ok": ok,
        "status": "ready" if ok else "unready",
        "database": db_status,
        "vector": vector_status,
        "milvus": milvus_status,
        "redis": redis_status,
        "minio": minio_status,
        "rag_runtime_warmup": rag_runtime_warmup_status,
        "dify_external_knowledge": dify_external_status,
    }
    status_code = 200 if ok else 503
    _ready_cache["ts"] = time.monotonic()
    _ready_cache["payload"] = payload
    _ready_cache["status"] = status_code
    _ready_cache["key"] = cache_key
    return payload, status_code, milvus_status


def _uploads_status() -> dict[str, Any]:
    status = {"status": "unknown", "path": settings.UPLOAD_DIR}
    try:
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        status["status"] = "ready"
    except Exception as exc:  # noqa: BLE001
        status["status"] = "unavailable"
        status["error"] = str(exc)[:200]
    return status


def _task_queue_status() -> dict[str, Any]:
    enabled = settings.TASK_QUEUE_ENABLED
    status = {
        "enabled": enabled,
        "queue": settings.TASK_QUEUE_NAME,
        "status": "disabled",
    }
    if enabled:
        initialized = is_queue_initialized()
        status["initialized"] = initialized
        status["status"] = "connected" if initialized else "not_initialized"
    return status


@router.get("/health", response_model=HealthResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "status": "ok",
    }


@router.get("/health/ready", response_model=ReadyResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def ready(response: Response) -> dict[str, Any]:
    """
    Readiness probe for orchestration (k8s, compose, etc).

    - Returns 200 when required deps are reachable
    - Returns 503 when one or more deps are down
    """
    payload, status_code, _milvus_status = _collect_ready_details()
    response.status_code = status_code
    return {"ok": bool(payload.get("ok")), "status": str(payload.get("status") or "unready")}


@router.get(
    "/health/details",
    response_model=HealthDetailsResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def health_details(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> dict[str, Any]:
    _ensure_admin(db, tenant_id, account_id)

    payload, status_code, milvus_status = _collect_ready_details()
    response.status_code = status_code
    return {
        **payload,
        "time": datetime.now(UTC).isoformat(),
        "vector_backend": settings.VECTOR_BACKEND,
        "use_langgraph_pipeline": settings.USE_LANGGRAPH_PIPELINE,
        "milvus": milvus_status,
        "task_queue": _task_queue_status(),
        "uploads": _uploads_status(),
    }
