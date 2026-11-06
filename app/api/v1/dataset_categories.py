"""Dataset categories API (tree + CRUD + move)."""

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
from app.models.dataset_category import DatasetCategory
from app.services import dataset_category_service

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
) -> DatasetCategoryTreeResponse:
    """List the tenant dataset category tree."""
    nodes = dataset_category_service.list_tree(db, tenant_id=tenant_id, account_id=account_id)
    # total categories (not just root nodes)
    try:
        total = db.query(DatasetCategory.id).filter(DatasetCategory.tenant_id == tenant_id).count()
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


@router.patch("/{category_id}", response_model=DatasetCategoryOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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


@router.post("/{category_id}/move", response_model=DatasetCategoryOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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


@router.delete("/{category_id}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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
