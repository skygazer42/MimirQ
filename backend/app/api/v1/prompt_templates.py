"""
Prompt template management API endpoints with tenant isolation.

This module provides REST API endpoints for managing prompt templates,
including CRUD operations and template duplication functionality.
All operations respect tenant boundaries and access control.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.sql import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.models.prompt_template import PromptTemplate
from app.api.schemas.prompt_template import (
    PromptTemplateCreate,
    PromptTemplateList,
    PromptTemplateNewVersion,
    PromptTemplateOut,
    PromptTemplateUpdate,
)
from app.services.dataset_service import DatasetService

router = APIRouter(tags=["prompt-templates"])


def _derive_template_key(name: str) -> str:
    """从名称派生一个稳定 key（尽量避免空 key）。"""
    raw = (name or "").strip().lower()
    if not raw:
        return "template"
    buf = []
    for ch in raw:
        if ch.isalnum():
            buf.append(ch)
        else:
            buf.append("_")
    key = "".join(buf).strip("_")
    while "__" in key:
        key = key.replace("__", "_")
    return key or "template"


@router.post("", response_model=PromptTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_prompt_template(
    request: PromptTemplateCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
) -> PromptTemplate:
    """
    Create a new prompt template.

    Creates a new user-defined prompt template within the current tenant's scope.
    System templates cannot be created through this endpoint.

    Args:
        request: Template creation data including name, content, and metadata
        tenant_id: Current tenant identifier (from auth context)
        account_id: Current user account identifier (from auth context)
        db: Database session

    Returns:
        The newly created prompt template with generated ID and timestamps

    Raises:
        HTTPException: 403 if user is not a tenant member
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    template_key = request.template_key or _derive_template_key(request.name)
    # 若同一 key 已存在版本，则默认递增版本号（便于平滑启用“版本化”能力）
    max_version = (
        db.query(func.max(PromptTemplate.version))
        .filter(PromptTemplate.tenant_id == tenant_id, PromptTemplate.template_key == template_key)
        .scalar()
    )
    next_version = int(max_version or 0) + 1

    template = PromptTemplate(
        tenant_id=tenant_id,
        template_key=template_key,
        version=next_version,
        parent_id=request.parent_id,
        ab_experiment_key=request.ab_experiment_key,
        ab_variant=request.ab_variant,
        ab_weight=float(request.ab_weight) if request.ab_weight is not None else 1.0,
        name=request.name,
        description=request.description,
        content=request.content,
        variables=request.variables,
        category=request.category,
        tags=request.tags,
        is_active=request.is_active,
        is_system=False,
    )

    db.add(template)
    db.commit()
    db.refresh(template)

    return template


@router.get("", response_model=PromptTemplateList)
async def list_prompt_templates(
    skip: int = 0,
    limit: int = 50,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
) -> PromptTemplateList:
    """
    List prompt templates with optional filtering and pagination.

    Retrieves prompt templates for the current tenant with support for
    filtering by category and active status. Results are ordered by
    system status, usage count, and update time.

    Args:
        skip: Number of records to skip for pagination (default: 0)
        limit: Maximum number of records to return (default: 50)
        category: Optional category filter
        is_active: Optional active status filter
        tenant_id: Current tenant identifier (from auth context)
        account_id: Current user account identifier (from auth context)
        db: Database session

    Returns:
        Paginated list of prompt templates with total count

    Raises:
        HTTPException: 403 if user is not a tenant member
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(PromptTemplate).filter(PromptTemplate.tenant_id == tenant_id)

    if category:
        query = query.filter(PromptTemplate.category == category)

    if is_active is not None:
        query = query.filter(PromptTemplate.is_active == is_active)

    total = query.count()

    templates = (
        query.order_by(
            PromptTemplate.is_system.desc(),
            PromptTemplate.usage_count.desc(),
            PromptTemplate.updated_at.desc(),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )

    return PromptTemplateList(total=total, items=templates)


@router.get("/{template_id}", response_model=PromptTemplateOut)
async def get_prompt_template(
    template_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
) -> PromptTemplate:
    """
    Retrieve a specific prompt template by ID.

    Args:
        template_id: Unique identifier of the template
        tenant_id: Current tenant identifier (from auth context)
        account_id: Current user account identifier (from auth context)
        db: Database session

    Returns:
        The requested prompt template

    Raises:
        HTTPException: 403 if user is not a tenant member
        HTTPException: 404 if template not found or not in current tenant
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    template = (
        db.query(PromptTemplate)
        .filter(
            PromptTemplate.id == template_id,
            PromptTemplate.tenant_id == tenant_id,
        )
        .first()
    )

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt template not found",
        )

    return template


@router.post(
    "/{template_id}/versions",
    response_model=PromptTemplateOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_prompt_template_version(
    template_id: UUID,
    request: PromptTemplateNewVersion,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
) -> PromptTemplate:
    """基于某个模板创建新版本（默认禁用旧版本）。"""
    DatasetService.ensure_member(db, tenant_id, account_id)

    current = (
        db.query(PromptTemplate)
        .filter(PromptTemplate.id == template_id, PromptTemplate.tenant_id == tenant_id)
        .first()
    )
    if not current:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt template not found")
    if current.is_system:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot version system templates")

    template_key = current.template_key or _derive_template_key(current.name)
    max_version = (
        db.query(func.max(PromptTemplate.version))
        .filter(PromptTemplate.tenant_id == tenant_id, PromptTemplate.template_key == template_key)
        .scalar()
    )
    next_version = int(max_version or 0) + 1

    if request.deactivate_previous:
        # 同一 key 的旧版本默认不再参与选择，避免“多活版本”带来的不可控差异
        db.query(PromptTemplate).filter(
            PromptTemplate.tenant_id == tenant_id,
            PromptTemplate.template_key == template_key,
        ).update({"is_active": False})

    new_template = PromptTemplate(
        tenant_id=tenant_id,
        template_key=template_key,
        version=next_version,
        parent_id=current.id,
        name=request.name or current.name,
        description=request.description if request.description is not None else current.description,
        content=request.content or current.content,
        variables=request.variables if request.variables is not None else (current.variables or []),
        category=request.category if request.category is not None else current.category,
        tags=request.tags if request.tags is not None else (current.tags or []),
        is_active=bool(request.is_active),
        is_system=False,
        ab_experiment_key=request.ab_experiment_key if request.ab_experiment_key is not None else current.ab_experiment_key,
        ab_variant=request.ab_variant if request.ab_variant is not None else current.ab_variant,
        ab_weight=float(request.ab_weight) if request.ab_weight is not None else float(current.ab_weight or 1.0),
        usage_count=0,
    )
    db.add(new_template)
    db.commit()
    db.refresh(new_template)
    return new_template


@router.put("/{template_id}", response_model=PromptTemplateOut)
async def update_prompt_template(
    template_id: UUID,
    request: PromptTemplateUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
) -> PromptTemplate:
    """
    Update an existing prompt template.

    Updates the specified template with new values. System templates
    cannot be modified through this endpoint.

    Args:
        template_id: Unique identifier of the template to update
        request: Update data (only provided fields will be updated)
        tenant_id: Current tenant identifier (from auth context)
        account_id: Current user account identifier (from auth context)
        db: Database session

    Returns:
        The updated prompt template

    Raises:
        HTTPException: 403 if user is not a tenant member or template is system template
        HTTPException: 404 if template not found
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    template = (
        db.query(PromptTemplate)
        .filter(
            PromptTemplate.id == template_id,
            PromptTemplate.tenant_id == tenant_id,
        )
        .first()
    )

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt template not found",
        )

    if template.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify system templates",
        )

    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(template, field, value)

    db.commit()
    db.refresh(template)

    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt_template(
    template_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a prompt template.

    Permanently deletes the specified template. System templates
    cannot be deleted through this endpoint.

    Args:
        template_id: Unique identifier of the template to delete
        tenant_id: Current tenant identifier (from auth context)
        account_id: Current user account identifier (from auth context)
        db: Database session

    Returns:
        None (HTTP 204 No Content on success)

    Raises:
        HTTPException: 403 if user is not a tenant member or template is system template
        HTTPException: 404 if template not found
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    template = (
        db.query(PromptTemplate)
        .filter(
            PromptTemplate.id == template_id,
            PromptTemplate.tenant_id == tenant_id,
        )
        .first()
    )

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt template not found",
        )

    if template.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete system templates",
        )

    db.delete(template)
    db.commit()


@router.post(
    "/{template_id}/duplicate",
    response_model=PromptTemplateOut,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_prompt_template(
    template_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
) -> PromptTemplate:
    """
    Duplicate an existing prompt template.

    Creates a copy of the specified template with a modified name.
    The duplicate is always created as a user template (not system).

    Args:
        template_id: Unique identifier of the template to duplicate
        tenant_id: Current tenant identifier (from auth context)
        account_id: Current user account identifier (from auth context)
        db: Database session

    Returns:
        The newly created duplicate template

    Raises:
        HTTPException: 403 if user is not a tenant member
        HTTPException: 404 if template not found
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    original = (
        db.query(PromptTemplate)
        .filter(
            PromptTemplate.id == template_id,
            PromptTemplate.tenant_id == tenant_id,
        )
        .first()
    )

    if not original:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt template not found",
        )

    duplicate = PromptTemplate(
        tenant_id=tenant_id,
        name=f"{original.name} (Copy)",
        description=original.description,
        content=original.content,
        variables=original.variables.copy() if original.variables else [],
        category=original.category,
        tags=original.tags.copy() if original.tags else [],
        is_active=True,
        is_system=False,
    )

    db.add(duplicate)
    db.commit()
    db.refresh(duplicate)

    return duplicate
