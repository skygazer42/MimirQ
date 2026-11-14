"""
Health check endpoints.

Public endpoints stay probe-friendly and minimal; detailed dependency state is admin-gated.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.system import HealthDetailsResponse, HealthResponse, ReadyResponse
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.health_checks import check_database, check_object_storage, check_redis, check_vector
from app.core.redis_client import LazyRedisClient
from app.services.health_readiness import get_ready_cache, store_ready_cache
from app.services.rag_runtime_warmup import (
    get_rag_runtime_warmup_status,
    rag_runtime_warmup_ready,
)
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission
from app.tasks.queue import is_queue_initialized

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)
_redis_client_slot = LazyRedisClient(
    url=lambda: settings.REDIS_URL,
    kwargs={
        "socket_timeout": 1,
        "socket_connect_timeout": 1,
        "decode_responses": True,
    },
    suppress_errors=False,
)


def _milvus_collection_count() -> int:
    # Import inside the callback so check_vector also handles optional SDK failures.
    from app.storage.vector.milvus import milvus_store

    return milvus_store.get_collection_count()


def _object_storage_probe_enabled() -> bool:
    from app.storage.object.runtime import document_object_storage_enabled

    return settings.MINIO_ENABLED or document_object_storage_enabled()


def _object_storage_health() -> dict[str, Any]:
    from app.storage.object.runtime import get_document_object_store

    store = get_document_object_store()
    if store is not None:
        return store.health_check()

    # MinIO may still serve extracted assets when document storage is disabled.
    from app.storage.object.minio import minio_service

    return minio_service.health_check()


def _ready_cache_key() -> tuple[object, ...]:
    return (
        settings.VECTOR_BACKEND.lower(),
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
        settings.REDIS_URL,
        settings.MILVUS_HOST,
        settings.MILVUS_PORT,
        settings.MINIO_ENDPOINT,
        settings.OBJECT_STORAGE_PROVIDER,
        settings.OBJECT_STORAGE_ENDPOINT,
        settings.OBJECT_STORAGE_BUCKET_NAME,
        settings.DATA_REGION,
        settings.OBJECT_STORAGE_REGION_PROFILES,
    )


def _collect_ready_details() -> tuple[dict[str, Any], int]:
    cache_key = _ready_cache_key()
    cached = get_ready_cache(cache_key)
    if cached is not None:
        return cached

    ok = True

    application_manages_schema = settings.DB_CREATE_ALL_ON_STARTUP or settings.DB_RUNTIME_MIGRATIONS_ENABLED
    db_status, db_ok = check_database(SessionLocal, require_schema_current=not application_manages_schema)
    ok &= db_ok

    vector_backend = settings.VECTOR_BACKEND.lower()
    vector_status, milvus_status, vector_ok = check_vector(
        settings,
        mode="ready",
        milvus_get_collection_count=_milvus_collection_count if vector_backend == "milvus" else None,
    )
    ok &= vector_ok

    redis_status, redis_ok, reset_client = check_redis(settings, get_client=_redis_client_slot.get)
    ok &= redis_ok
    if reset_client:
        _redis_client_slot.invalidate()

    minio_status, minio_ok = check_object_storage(
        is_enabled=_object_storage_probe_enabled,
        health_check=_object_storage_health,
    )
    ok &= minio_ok

    rag_runtime_warmup_status = get_rag_runtime_warmup_status()
    rag_runtime_warmup_status["required_for_ready"] = settings.RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY
    if settings.RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY:
        ok &= rag_runtime_warmup_ready()

    dify_external_status = None
    if settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED:
        try:
            from app.services.dify_integration.warmup_state import (
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
    store_ready_cache(payload, status_code, cache_key)
    return payload, status_code


def _uploads_status() -> dict[str, Any]:
    try:
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "path": settings.UPLOAD_DIR, "error": str(exc)[:200]}
    return {"status": "ready", "path": settings.UPLOAD_DIR}


def _task_queue_status() -> dict[str, Any]:
    if not settings.TASK_QUEUE_ENABLED:
        return {"enabled": False, "queue": settings.TASK_QUEUE_NAME, "status": "disabled"}

    initialized = is_queue_initialized()
    return {
        "enabled": True,
        "queue": settings.TASK_QUEUE_NAME,
        "status": "connected" if initialized else "not_initialized",
        "initialized": initialized,
    }


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(ok=True, status="ok")


@router.get("/health/ready", response_model=ReadyResponse)
def ready(response: Response) -> ReadyResponse:
    """
    Readiness probe for orchestration (k8s, compose, etc).

    - Returns 200 when required deps are reachable
    - Returns 503 when one or more deps are down
    """
    payload, status_code = _collect_ready_details()
    response.status_code = status_code
    return ReadyResponse(ok=payload["ok"], status=payload["status"])


@router.get(
    "/health/details",
    response_model=HealthDetailsResponse,
)
def health_details(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> HealthDetailsResponse:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.OBSERVABILITY_READ,
        detail="No permission to access observability dashboards",
    )

    payload, status_code = _collect_ready_details()
    response.status_code = status_code
    return HealthDetailsResponse(
        **payload,
        time=datetime.now(UTC).isoformat(),
        vector_backend=settings.VECTOR_BACKEND,
        use_langgraph_pipeline=settings.USE_LANGGRAPH_PIPELINE,
        task_queue=_task_queue_status(),
        uploads=_uploads_status(),
    )
