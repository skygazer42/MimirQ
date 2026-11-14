"""
Backend metadata endpoints for frontend/dev tooling.
"""

import platform
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.system import (
    BuildMeta,
    MetaDetailsResponse,
    MetaFeatureFlags,
    MetaResponse,
    PublicMetaFeatureFlags,
    RuntimeMeta,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.build_info import get_build_sha, get_build_time
from app.core.config import settings
from app.core.database import get_db
from app.core.utils import parse_csv
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _build_public_meta() -> MetaResponse:
    return MetaResponse(
        name="Ragvia",
        api_version="v1",
        build=BuildMeta(sha=get_build_sha(), time=get_build_time()),
        features=PublicMetaFeatureFlags(auth_mode=settings.AUTH_MODE),
    )


@router.get("/meta", response_model=MetaResponse)
def get_meta() -> MetaResponse:
    """Small, safe-to-expose metadata endpoint for UI diagnostics."""
    return _build_public_meta()


@router.get("/meta/details", response_model=MetaDetailsResponse)
def get_meta_details(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> MetaDetailsResponse:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.OBSERVABILITY_READ,
        detail="No permission to access observability dashboards",
    )
    public = _build_public_meta()
    return MetaDetailsResponse(
        name=public.name,
        api_version=public.api_version,
        build=public.build,
        time=datetime.now(UTC).isoformat(),
        features=MetaFeatureFlags(
            auth_mode=settings.AUTH_MODE,
            vector_backend=settings.VECTOR_BACKEND,
            kg_enabled=settings.KG_ENABLED,
            task_queue_enabled=settings.TASK_QUEUE_ENABLED,
            embedding_cache_enabled=settings.EMBEDDING_CACHE_ENABLED,
            minio_enabled=settings.MINIO_ENABLED,
            use_langgraph_pipeline=settings.USE_LANGGRAPH_PIPELINE,
            gzip_enabled=settings.GZIP_ENABLED,
            rate_limit_enabled=settings.RATE_LIMIT_ENABLED,
            cors_origins=parse_csv(settings.CORS_ORIGINS),
        ),
        runtime=RuntimeMeta(python=platform.python_version(), platform=platform.platform()),
    )
