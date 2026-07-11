"""
Backend metadata endpoints for frontend/dev tooling.
"""


import os
import platform
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.meta import MetaDetailsResponse, MetaResponse
from app.core.config import settings
from app.core.database import get_db
from app.core.utils import parse_csv
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _ensure_admin(db: Session, tenant_id: UUID, account_id: str) -> None:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.OBSERVABILITY_READ,
        detail="No permission to access observability dashboards",
    )


def _get_build_sha() -> str | None:
    value = (
        os.getenv("MIMIRQ_BUILD_SHA")
        or os.getenv("GIT_SHA")
        or os.getenv("SOURCE_VERSION")
        or os.getenv("GITHUB_SHA")
        or ""
    ).strip()
    return value or None


def _get_build_time() -> str | None:
    value = (os.getenv("MIMIRQ_BUILD_TIME") or os.getenv("BUILD_TIME") or "").strip()
    return value or None


def _build_public_meta() -> dict[str, Any]:
    return {
        "name": "MimirQ",
        "api_version": "v1",
        "build": {
            "sha": _get_build_sha(),
            "time": _get_build_time(),
        },
        "features": {
            "auth_mode": str(getattr(settings, "AUTH_MODE", "header") or "header"),
        },
    }


def _build_detailed_meta() -> dict[str, Any]:
    return {
        **_build_public_meta(),
        "time": datetime.now(UTC).isoformat(),
        "features": {
            "auth_mode": str(getattr(settings, "AUTH_MODE", "header") or "header"),
            "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus"),
            "kg_enabled": bool(getattr(settings, "KG_ENABLED", False)),
            "task_queue_enabled": bool(getattr(settings, "TASK_QUEUE_ENABLED", False)),
            "embedding_cache_enabled": bool(getattr(settings, "EMBEDDING_CACHE_ENABLED", False)),
            "minio_enabled": bool(getattr(settings, "MINIO_ENABLED", False)),
            "use_langgraph_pipeline": bool(getattr(settings, "USE_LANGGRAPH_PIPELINE", False)),
            "gzip_enabled": bool(getattr(settings, "GZIP_ENABLED", True)),
            "rate_limit_enabled": bool(getattr(settings, "RATE_LIMIT_ENABLED", False)),
            "cors_origins": parse_csv(getattr(settings, "CORS_ORIGINS", "")),
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }


@router.get("/meta", response_model=MetaResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_meta() -> dict[str, Any]:
    """
    Small, safe-to-expose metadata endpoint for UI diagnostics.
    """
    return _build_public_meta()


@router.get("/meta/details", response_model=MetaDetailsResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_meta_details(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> dict[str, Any]:
    _ensure_admin(db, tenant_id, account_id)
    return _build_detailed_meta()
