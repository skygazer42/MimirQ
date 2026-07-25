"""
LTR model registry API.

Provides a small, file-based registry for LTR reranker artifacts:
- versioned storage (sha256-addressed)
- manifest validation (feature schema + sha256 pin)
- activation + one-step rollback controls
"""


from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.rag.core.logging import get_logger
from app.services.audit_log_service import audit_log_event
from app.services.ltr_model_registry import (
    activate_model,
    list_models,
    register_model,
    resolve_active_model_paths,
    rollback_active_model,
)
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)
_LTR_ROUTER_FALLBACK_LOG_MESSAGE = "Ignoring non-critical LTR router fallback failure: %s"

_NO_PERMISSION_TO_MANAGE_LTR_MODELS_DETAIL = "No permission to manage LTR models"


class LTRModelInfo(BaseModel):
    model_id: str
    model_sha256: str
    size_bytes: int = 0
    created_at: str = ""
    created_by: str | None = None
    feature_spec_version: int = 1
    feature_schema: str = ""
    feature_names: list[str] = Field(default_factory=list)
    has_manifest: bool = True
    active: bool = False


class LTRModelListResponse(BaseModel):
    items: list[LTRModelInfo] = Field(default_factory=list)


class LTRModelRegisterResponse(BaseModel):
    model: LTRModelInfo


class LTRModelActivateRequest(BaseModel):
    model_id: str


class LTRModelActivateResponse(BaseModel):
    active: dict[str, Any]


@router.get("/models", response_model=LTRModelListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_ltr_models(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_READ,
        detail="No permission to access LTR model registry",
    )

    mp, _man, _spec_v, active_id = resolve_active_model_paths()
    _ = mp  # active is identified by model_id, not runtime path.
    active_id = str(active_id or "").strip().lower() or None

    items_out: list[LTRModelInfo] = []
    for m in list_models():
        items_out.append(
            LTRModelInfo(
                model_id=m.model_id,
                model_sha256=m.model_sha256,
                size_bytes=m.size_bytes,
                created_at=m.created_at,
                created_by=m.created_by,
                feature_spec_version=m.feature_spec_version,
                feature_schema=m.feature_schema,
                feature_names=list(m.feature_names or []),
                has_manifest=bool(m.has_manifest),
                active=(active_id is not None and str(m.model_id).strip().lower() == active_id),
            )
        )

    return LTRModelListResponse(items=items_out)


@router.post("/models/register", response_model=LTRModelRegisterResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def register_ltr_model(
    model_file: Annotated[UploadFile, File(..., description='XGBoost model bytes (JSON)')],
    manifest_file: Annotated[UploadFile, File(..., description='LTR manifest JSON (validated)')],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail=_NO_PERMISSION_TO_MANAGE_LTR_MODELS_DETAIL,
    )

    try:
        model_bytes = await model_file.read()
        manifest_bytes = await manifest_file.read()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to read upload: {str(exc)[:160]}") from exc

    try:
        reg = register_model(model_bytes=model_bytes, manifest_bytes=manifest_bytes, actor_id=account_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)[:200]) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:200]) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to register model: {str(exc)[:200]}") from exc

    # Best-effort audit log (PII-safe; hashes only).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="ltr_model.register",
            resource_type="ltr_model",
            resource_id=str(reg.model_id)[:255],
            details={
                "model_sha256": str(reg.model_sha256)[:64],
                "size_bytes": int(reg.size_bytes),
                "feature_spec_version": int(reg.feature_spec_version),
            },
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(_LTR_ROUTER_FALLBACK_LOG_MESSAGE, exc)

    return LTRModelRegisterResponse(
        model=LTRModelInfo(
            model_id=reg.model_id,
            model_sha256=reg.model_sha256,
            size_bytes=reg.size_bytes,
            created_at=reg.created_at,
            created_by=reg.created_by,
            feature_spec_version=reg.feature_spec_version,
            feature_schema=reg.feature_schema,
            feature_names=list(reg.feature_names or []),
            has_manifest=bool(reg.has_manifest),
            active=False,
        )
    )


@router.post("/models/activate", response_model=LTRModelActivateResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def activate_ltr_model(
    body: LTRModelActivateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail=_NO_PERMISSION_TO_MANAGE_LTR_MODELS_DETAIL,
    )

    try:
        active = activate_model(model_id=body.model_id, actor_id=account_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)[:200]) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:200]) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to activate model: {str(exc)[:200]}") from exc

    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="ltr_model.activate",
            resource_type="ltr_model",
            resource_id=str(body.model_id)[:255],
            details={"active": dict(active or {})},
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(_LTR_ROUTER_FALLBACK_LOG_MESSAGE, exc)

    return LTRModelActivateResponse(active=dict(active or {}))


@router.post("/models/rollback", response_model=LTRModelActivateResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def rollback_ltr_model(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail=_NO_PERMISSION_TO_MANAGE_LTR_MODELS_DETAIL,
    )

    try:
        active = rollback_active_model(actor_id=account_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)[:200]) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:200]) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to rollback model: {str(exc)[:200]}") from exc

    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="ltr_model.rollback",
            resource_type="ltr_model",
            resource_id=str(active.get("current_model_id") or "")[:255],
            details={"active": dict(active or {})},
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(_LTR_ROUTER_FALLBACK_LOG_MESSAGE, exc)

    return LTRModelActivateResponse(active=dict(active or {}))
