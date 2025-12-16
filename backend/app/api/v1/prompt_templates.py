"""
Prompt template management API with tenant isolation.
"""
from uuid import UUID
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.prompt_template import PromptTemplate
from app.schemas.prompt_template import (
    PromptTemplateCreate,
    PromptTemplateUpdate,
    PromptTemplateOut,
    PromptTemplateList,
)
from app.dependencies.tenant import get_tenant_id
from app.dependencies.auth import get_current_account_id
from app.services.dataset_service import DatasetService

router = APIRouter()


@router.post("", response_model=PromptTemplateOut, status_code=201)
async def create_prompt_template(
    request: PromptTemplateCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """Create a new prompt template"""
    # Ensure user is tenant member
    DatasetService.ensure_member(db, tenant_id, account_id)

    # Create template
    template = PromptTemplate(
        tenant_id=tenant_id,
        name=request.name,
        description=request.description,
        content=request.content,
        variables=request.variables,
        category=request.category,
        tags=request.tags,
        is_active=request.is_active,
        is_system=False,  # User-created templates are never system templates
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
    db: Session = Depends(get_db)
):
    """List all prompt templates for the tenant"""
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(PromptTemplate).filter(PromptTemplate.tenant_id == tenant_id)

    if category:
        query = query.filter(PromptTemplate.category == category)

    if is_active is not None:
        query = query.filter(PromptTemplate.is_active == is_active)

    total = query.count()

    templates = query.order_by(
        PromptTemplate.is_system.desc(),  # System templates first
        PromptTemplate.usage_count.desc(),  # Then by usage
        PromptTemplate.updated_at.desc()
    ).offset(skip).limit(limit).all()

    return {
        "total": total,
        "items": templates
    }


@router.get("/{template_id}", response_model=PromptTemplateOut)
async def get_prompt_template(
    template_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """Get a specific prompt template"""
    DatasetService.ensure_member(db, tenant_id, account_id)

    template = db.query(PromptTemplate).filter(
        PromptTemplate.id == template_id,
        PromptTemplate.tenant_id == tenant_id
    ).first()

    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")

    return template


@router.put("/{template_id}", response_model=PromptTemplateOut)
async def update_prompt_template(
    template_id: UUID,
    request: PromptTemplateUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """Update a prompt template"""
    DatasetService.ensure_member(db, tenant_id, account_id)

    template = db.query(PromptTemplate).filter(
        PromptTemplate.id == template_id,
        PromptTemplate.tenant_id == tenant_id
    ).first()

    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")

    # Prevent modifying system templates
    if template.is_system:
        raise HTTPException(status_code=403, detail="Cannot modify system templates")

    # Update fields
    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(template, field, value)

    db.commit()
    db.refresh(template)

    return template


@router.delete("/{template_id}", status_code=204)
async def delete_prompt_template(
    template_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """Delete a prompt template"""
    DatasetService.ensure_member(db, tenant_id, account_id)

    template = db.query(PromptTemplate).filter(
        PromptTemplate.id == template_id,
        PromptTemplate.tenant_id == tenant_id
    ).first()

    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")

    # Prevent deleting system templates
    if template.is_system:
        raise HTTPException(status_code=403, detail="Cannot delete system templates")

    db.delete(template)
    db.commit()

    return None


@router.post("/{template_id}/duplicate", response_model=PromptTemplateOut, status_code=201)
async def duplicate_prompt_template(
    template_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """Duplicate an existing prompt template"""
    DatasetService.ensure_member(db, tenant_id, account_id)

    original = db.query(PromptTemplate).filter(
        PromptTemplate.id == template_id,
        PromptTemplate.tenant_id == tenant_id
    ).first()

    if not original:
        raise HTTPException(status_code=404, detail="Prompt template not found")

    # Create duplicate
    duplicate = PromptTemplate(
        tenant_id=tenant_id,
        name=f"{original.name} (Copy)",
        description=original.description,
        content=original.content,
        variables=original.variables.copy() if original.variables else [],
        category=original.category,
        tags=original.tags.copy() if original.tags else [],
        is_active=True,
        is_system=False,  # Duplicates are never system templates
    )

    db.add(duplicate)
    db.commit()
    db.refresh(duplicate)

    return duplicate
