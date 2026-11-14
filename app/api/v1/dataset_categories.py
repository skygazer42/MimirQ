"""Dataset categories API (tree + CRUD + move)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.datasets import (
    DatasetCategoryCreate,
    DatasetCategoryMoveRequest,
    DatasetCategoryOut,
    DatasetCategoryTreeResponse,
    DatasetCategoryUpdate,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.services import dataset_category_service

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/", response_model=DatasetCategoryTreeResponse)
def list_dataset_categories(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DatasetCategoryTreeResponse:
    """List the tenant dataset category tree."""
    return dataset_category_service.list_tree(db, tenant_id=tenant_id, account_id=account_id)


@router.post("/", response_model=DatasetCategoryOut, status_code=201)
def create_dataset_category(
    payload: DatasetCategoryCreate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DatasetCategoryOut:
    """Create a dataset category."""
    row = dataset_category_service.create_category(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        name=payload.name,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
    )
    return DatasetCategoryOut.model_validate(row)


@router.patch("/{category_id}", response_model=DatasetCategoryOut)
def update_dataset_category(
    category_id: UUID,
    payload: DatasetCategoryUpdate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DatasetCategoryOut:
    """Update a dataset category."""
    row = dataset_category_service.update_category(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        category_id=category_id,
        name=payload.name,
        sort_order=payload.sort_order,
    )
    return DatasetCategoryOut.model_validate(row)


@router.post("/{category_id}/move", response_model=DatasetCategoryOut)
def move_dataset_category(
    category_id: UUID,
    payload: DatasetCategoryMoveRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DatasetCategoryOut:
    """Move a dataset category within the tree."""
    row = dataset_category_service.move_category(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        category_id=category_id,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
    )
    return DatasetCategoryOut.model_validate(row)


@router.delete("/{category_id}", status_code=204)
def delete_dataset_category(
    category_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Delete a dataset category."""
    dataset_category_service.delete_category(db, tenant_id=tenant_id, account_id=account_id, category_id=category_id)
    return Response(status_code=204)
