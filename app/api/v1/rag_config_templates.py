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

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.conversations import (
    RagConfigTemplateCreate,
    RagConfigTemplateList,
    RagConfigTemplateListQuery,
    RagConfigTemplateNewVersion,
    RagConfigTemplateOut,
    RagConfigTemplateUpdate,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.models.rag_config_template import RagConfigTemplate
from app.services import dataset_service
from app.services.rag_config_template_apply import validate_rag_config_patch
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

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
    key = "".join(character if character.isalnum() else "_" for character in name.strip().lower())
    return "_".join(part for part in key.split("_") if part) or "rag_config"


@router.post(
    "",
    response_model=RagConfigTemplateOut,
    status_code=status.HTTP_201_CREATED,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def create_rag_config_template(
    request: RagConfigTemplateCreate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagConfigTemplate:
    dataset_service.ensure_member(db, tenant_id, account_id)
    _ensure_write(db, tenant_id, account_id)

    config_patch = request.config_patch.model_dump(exclude_none=True)
    validate_rag_config_patch(config_patch)

    template_key = request.template_key or _derive_template_key(request.name)
    max_version = (
        db.query(func.max(RagConfigTemplate.version))
        .filter(RagConfigTemplate.tenant_id == tenant_id, RagConfigTemplate.template_key == template_key)
        .scalar()
    )
    next_version = 1 if max_version is None else max_version + 1

    template = RagConfigTemplate(
        tenant_id=tenant_id,
        template_key=template_key,
        version=next_version,
        parent_id=request.parent_id,
        ab_experiment_key=request.ab_experiment_key,
        ab_variant=request.ab_variant,
        ab_weight=request.ab_weight if request.ab_weight is not None else 1.0,
        name=request.name,
        description=request.description,
        config_patch=config_patch,
        is_active=request.is_active,
    )

    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.get("", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_rag_config_templates(
    filters: Annotated[RagConfigTemplateListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagConfigTemplateList:
    dataset_service.ensure_member(db, tenant_id, account_id)
    _ensure_read(db, tenant_id, account_id)

    query = db.query(RagConfigTemplate).filter(RagConfigTemplate.tenant_id == tenant_id)

    if filters.template_key:
        query = query.filter(RagConfigTemplate.template_key == filters.template_key.strip())
    if filters.ab_experiment_key:
        query = query.filter(RagConfigTemplate.ab_experiment_key == filters.ab_experiment_key.strip())
    if filters.is_active is not None:
        query = query.filter(RagConfigTemplate.is_active == filters.is_active)

    total = query.count()
    items = (
        query.order_by(
            RagConfigTemplate.template_key.asc().nullslast(),
            RagConfigTemplate.version.desc(),
            RagConfigTemplate.updated_at.desc(),
        )
        .offset(filters.skip)
        .limit(filters.limit)
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
    dataset_service.ensure_member(db, tenant_id, account_id)
    _ensure_read(db, tenant_id, account_id)

    template = (
        db.query(RagConfigTemplate)
        .filter(RagConfigTemplate.id == template_id, RagConfigTemplate.tenant_id == tenant_id)
        .first()
    )
    if template is None:
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
    dataset_service.ensure_member(db, tenant_id, account_id)
    _ensure_write(db, tenant_id, account_id)

    template = (
        db.query(RagConfigTemplate)
        .filter(RagConfigTemplate.id == template_id, RagConfigTemplate.tenant_id == tenant_id)
        .first()
    )
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_RAG_CONFIG_TEMPLATE_NOT_FOUND_DETAIL)

    effective_patch = (
        request.config_patch.model_dump(exclude_none=True)
        if request.config_patch is not None
        else (template.config_patch or {})
    )
    active_after_update = request.is_active if request.is_active is not None else template.is_active
    if request.config_patch is not None or active_after_update:
        validate_rag_config_patch(effective_patch)

    if request.template_key is not None:
        template.template_key = request.template_key.strip()
    if request.name is not None:
        template.name = request.name.strip()
    if request.description is not None:
        template.description = request.description
    if request.config_patch is not None:
        template.config_patch = effective_patch
    if request.is_active is not None:
        template.is_active = request.is_active
    if request.version is not None:
        template.version = request.version
    if request.parent_id is not None:
        template.parent_id = request.parent_id
    if request.ab_experiment_key is not None:
        template.ab_experiment_key = request.ab_experiment_key.strip()
    if request.ab_variant is not None:
        template.ab_variant = request.ab_variant.strip()
    if request.ab_weight is not None:
        template.ab_weight = request.ab_weight

    db.commit()
    db.refresh(template)
    return template


@router.post(
    "/{template_id}/versions",
    response_model=RagConfigTemplateOut,
    status_code=status.HTTP_201_CREATED,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def create_rag_config_template_version(
    template_id: UUID,
    request: RagConfigTemplateNewVersion,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagConfigTemplate:
    dataset_service.ensure_member(db, tenant_id, account_id)
    _ensure_write(db, tenant_id, account_id)

    current = (
        db.query(RagConfigTemplate)
        .filter(RagConfigTemplate.id == template_id, RagConfigTemplate.tenant_id == tenant_id)
        .first()
    )
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_RAG_CONFIG_TEMPLATE_NOT_FOUND_DETAIL)

    effective_patch = (
        request.config_patch.model_dump(exclude_none=True)
        if request.config_patch is not None
        else (current.config_patch or {})
    )
    validate_rag_config_patch(effective_patch)

    template_key = current.template_key or _derive_template_key(current.name)
    max_version = (
        db.query(func.max(RagConfigTemplate.version))
        .filter(RagConfigTemplate.tenant_id == tenant_id, RagConfigTemplate.template_key == template_key)
        .scalar()
    )
    next_version = 1 if max_version is None else max_version + 1

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
        name=request.name if request.name is not None else current.name,
        description=request.description if request.description is not None else current.description,
        config_patch=effective_patch,
        is_active=request.is_active,
        ab_experiment_key=request.ab_experiment_key
        if request.ab_experiment_key is not None
        else current.ab_experiment_key,
        ab_variant=request.ab_variant if request.ab_variant is not None else current.ab_variant,
        ab_weight=request.ab_weight,
    )

    db.add(new_template)
    db.commit()
    db.refresh(new_template)
    return new_template


__all__ = ["router"]
