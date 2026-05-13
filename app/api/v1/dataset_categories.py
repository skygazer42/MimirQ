"""Dataset categories API (tree + CRUD + move)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.dataset_category import (
    DatasetCategoryCreate,
    DatasetCategoryMoveRequest,
    DatasetCategoryOut,
    DatasetCategoryTreeResponse,
    DatasetCategoryUpdate,
)
from app.core.database import get_db
from app.services.dataset_category_service import DatasetCategoryService

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/", response_model=DatasetCategoryTreeResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_dataset_categories(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """List the tenant dataset category tree."""
    nodes = DatasetCategoryService.list_tree(db, tenant_id=tenant_id, account_id=account_id)
    # total categories (not just root nodes)
    total = 0
    try:
        from app.models.dataset_category import DatasetCategory

        total = int(db.query(DatasetCategory.id).filter(DatasetCategory.tenant_id == tenant_id).count() or 0)
    except Exception:
        total = 0
    return DatasetCategoryTreeResponse(total=total, items=nodes)


@router.post("/", response_model=DatasetCategoryOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_dataset_category(
    payload: DatasetCategoryCreate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a dataset category."""
    row = DatasetCategoryService.create(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        name=payload.name,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
    )
    return DatasetCategoryOut.model_validate(row)


@router.patch("/{category_id}", response_model=DatasetCategoryOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def update_dataset_category(
    category_id: UUID,
    payload: DatasetCategoryUpdate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Update a dataset category."""
    row = DatasetCategoryService.update(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        category_id=category_id,
        name=payload.name,
        sort_order=payload.sort_order,
    )
    return DatasetCategoryOut.model_validate(row)


@router.post("/{category_id}/move", response_model=DatasetCategoryOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def move_dataset_category(
    category_id: UUID,
    payload: DatasetCategoryMoveRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Move a dataset category within the tree."""
    row = DatasetCategoryService.move(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        category_id=category_id,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
    )
    return DatasetCategoryOut.model_validate(row)


@router.delete("/{category_id}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_dataset_category(
    category_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Delete a dataset category."""
    DatasetCategoryService.delete(db, tenant_id=tenant_id, account_id=account_id, category_id=category_id)
    return Response(status_code=204)
