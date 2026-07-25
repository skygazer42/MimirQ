"""
RAG config template management API endpoints.

These templates provide versioned retrieval/rerank config patches that can be used for:
- safe rollout via A/B experiment keys + weights
- quick rollback via switching dataset defaults or toggling is_active

All operations are tenant-isolated and admin-gated (settings.write / settings.read).
"""


from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.rag_config_template import (
    RagConfigTemplateCreate,
    RagConfigTemplateList,
    RagConfigTemplateNewVersion,
    RagConfigTemplateOut,
    RagConfigTemplateUpdate,
)
from app.core.database import get_db
from app.models.rag_config_template import RagConfigTemplate
from app.services.dataset_service import DatasetService
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(tags=["RAG Config Templates"], responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_RAG_CONFIG_TEMPLATE_NOT_FOUND_DETAIL = "RAG config template not found"


def _ensure_read(db: Session, tenant_id: UUID, account_id: str) -> None:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_READ,
        detail="No permission to access RAG config templates",
    )


def _ensure_write(db: Session, tenant_id: UUID, account_id: str) -> None:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail="No permission to manage RAG config templates",
    )


def _derive_template_key(name: str) -> str:
    raw = (name or "").strip().lower()
    if not raw:
        return "rag_config"
    buf = []
    for ch in raw:
        buf.append(ch if ch.isalnum() else "_")
    key = "".join(buf).strip("_")
    while "__" in key:
        key = key.replace("__", "_")
    return key or "rag_config"


@router.post("", response_model=RagConfigTemplateOut, status_code=status.HTTP_201_CREATED, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_rag_config_template(
    request: RagConfigTemplateCreate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagConfigTemplate:
    DatasetService.ensure_member(db, tenant_id, account_id)
    _ensure_write(db, tenant_id, account_id)

    template_key = request.template_key or _derive_template_key(request.name)
    max_version = (
        db.query(func.max(RagConfigTemplate.version))
        .filter(RagConfigTemplate.tenant_id == tenant_id, RagConfigTemplate.template_key == template_key)
        .scalar()
    )
    next_version = int(max_version or 0) + 1

    template = RagConfigTemplate(
        tenant_id=tenant_id,
        template_key=template_key,
        version=next_version,
        parent_id=request.parent_id,
        ab_experiment_key=request.ab_experiment_key,
        ab_variant=request.ab_variant,
        ab_weight=float(request.ab_weight) if request.ab_weight is not None else 1.0,
        name=request.name,
        description=request.description,
        config_patch=(request.config_patch.model_dump(exclude_none=True) if request.config_patch is not None else {}),
        is_active=bool(request.is_active),
    )

    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.get("", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_rag_config_templates(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    template_key: str | None = None,
    ab_experiment_key: str | None = None,
    is_active: bool | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagConfigTemplateList:
    DatasetService.ensure_member(db, tenant_id, account_id)
    _ensure_read(db, tenant_id, account_id)

    query = db.query(RagConfigTemplate).filter(RagConfigTemplate.tenant_id == tenant_id)

    if template_key:
        query = query.filter(RagConfigTemplate.template_key == str(template_key).strip())
    if ab_experiment_key:
        query = query.filter(RagConfigTemplate.ab_experiment_key == str(ab_experiment_key).strip())
    if is_active is not None:
        query = query.filter(RagConfigTemplate.is_active == bool(is_active))

    total = query.count()
    items = (
        query.order_by(
            RagConfigTemplate.template_key.asc().nullslast(),
            RagConfigTemplate.version.desc(),
            RagConfigTemplate.updated_at.desc(),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )
    return RagConfigTemplateList(total=total, items=items)


@router.get("/{template_id}", response_model=RagConfigTemplateOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_rag_config_template(
    template_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagConfigTemplate:
    DatasetService.ensure_member(db, tenant_id, account_id)
    _ensure_read(db, tenant_id, account_id)

    template = (
        db.query(RagConfigTemplate)
        .filter(RagConfigTemplate.id == template_id, RagConfigTemplate.tenant_id == tenant_id)
        .first()
    )
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_RAG_CONFIG_TEMPLATE_NOT_FOUND_DETAIL)
    return template


@router.patch("/{template_id}", response_model=RagConfigTemplateOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def update_rag_config_template(
    template_id: UUID,
    request: RagConfigTemplateUpdate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagConfigTemplate:
    DatasetService.ensure_member(db, tenant_id, account_id)
    _ensure_write(db, tenant_id, account_id)

    template = (
        db.query(RagConfigTemplate)
        .filter(RagConfigTemplate.id == template_id, RagConfigTemplate.tenant_id == tenant_id)
        .first()
    )
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_RAG_CONFIG_TEMPLATE_NOT_FOUND_DETAIL)

    if request.template_key is not None:
        template.template_key = str(request.template_key or "").strip() or None
    if request.name is not None:
        template.name = str(request.name or "").strip()[:200] or template.name
    if request.description is not None:
        template.description = request.description
    if request.config_patch is not None:
        template.config_patch = request.config_patch.model_dump(exclude_none=True)
    if request.is_active is not None:
        template.is_active = bool(request.is_active)
    if request.version is not None:
        template.version = int(request.version)
    if request.parent_id is not None:
        template.parent_id = request.parent_id
    if request.ab_experiment_key is not None:
        template.ab_experiment_key = str(request.ab_experiment_key or "").strip() or None
    if request.ab_variant is not None:
        template.ab_variant = str(request.ab_variant or "").strip()[:50] or None
    if request.ab_weight is not None:
        template.ab_weight = float(request.ab_weight)

    db.commit()
    db.refresh(template)
    return template


@router.post("/{template_id}/versions", response_model=RagConfigTemplateOut, status_code=status.HTTP_201_CREATED, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_rag_config_template_version(
    template_id: UUID,
    request: RagConfigTemplateNewVersion,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagConfigTemplate:
    DatasetService.ensure_member(db, tenant_id, account_id)
    _ensure_write(db, tenant_id, account_id)

    current = (
        db.query(RagConfigTemplate)
        .filter(RagConfigTemplate.id == template_id, RagConfigTemplate.tenant_id == tenant_id)
        .first()
    )
    if not current:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_RAG_CONFIG_TEMPLATE_NOT_FOUND_DETAIL)

    template_key = current.template_key or _derive_template_key(current.name)
    max_version = (
        db.query(func.max(RagConfigTemplate.version))
        .filter(RagConfigTemplate.tenant_id == tenant_id, RagConfigTemplate.template_key == template_key)
        .scalar()
    )
    next_version = int(max_version or 0) + 1

    if request.deactivate_previous:
        db.query(RagConfigTemplate).filter(
            RagConfigTemplate.tenant_id == tenant_id,
            RagConfigTemplate.template_key == template_key,
        ).update({"is_active": False})

    new_template = RagConfigTemplate(
        tenant_id=tenant_id,
        template_key=template_key,
        version=next_version,
        parent_id=current.id,
        name=request.name or current.name,
        description=request.description if request.description is not None else current.description,
        config_patch=(
            request.config_patch.model_dump(exclude_none=True)
            if request.config_patch is not None
            else (current.config_patch or {})
        ),
        is_active=bool(request.is_active),
        ab_experiment_key=request.ab_experiment_key if request.ab_experiment_key is not None else current.ab_experiment_key,
        ab_variant=request.ab_variant if request.ab_variant is not None else current.ab_variant,
        ab_weight=float(request.ab_weight or 1.0),
    )

    db.add(new_template)
    db.commit()
    db.refresh(new_template)
    return new_template


__all__ = ["router"]
