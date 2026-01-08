"""
Dataset management API.
Supports dataset creation, query, update, deletion, and permission management.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.database import get_db
from app.api.dependencies.tenant import get_tenant_id
from app.api.dependencies.auth import get_current_account_id
from app.api.schemas.dataset import DatasetCreate, DatasetUpdate, DatasetOut, DatasetListResponse
from app.models.dataset import DatasetPermissionEnum, DatasetPermission
from app.services.dataset_service import DatasetService, DatasetPermissionService
from app.models.dataset import Dataset

router = APIRouter()


@router.post("/", response_model=DatasetOut, status_code=201)
def create_dataset(
    payload: DatasetCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    dataset = DatasetService.create_dataset(
        db=db,
        tenant_id=tenant_id,
        name=payload.name,
        description=payload.description,
        permission=payload.permission,
        owner_id=account_id,
        partial_members=payload.partial_member_list or [],
    )

    partial_list = None
    if dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
        partial_list = payload.partial_member_list or []

    return DatasetOut(
        id=dataset.id,
        tenant_id=dataset.tenant_id,
        name=dataset.name,
        description=dataset.description,
        permission=dataset.permission,
        owner_id=dataset.owner_id,
        partial_member_list=partial_list
    )


@router.get("/", response_model=DatasetListResponse)
def list_datasets(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    # list all datasets in tenant
    query = db.query(Dataset).filter(Dataset.tenant_id == tenant_id)
    total = query.count()
    datasets = query.order_by(Dataset.created_at.desc()).offset(skip).limit(limit).all()

    # Avoid N+1 queries for PARTIAL_MEMBERS datasets
    partial_ids = [ds.id for ds in datasets if ds.permission == DatasetPermissionEnum.PARTIAL_MEMBERS]
    partial_member_map = {}
    if partial_ids:
        rows = (
            db.query(DatasetPermission)
            .filter(
                DatasetPermission.tenant_id == tenant_id,
                DatasetPermission.dataset_id.in_(partial_ids),
            )
            .all()
        )
        from collections import defaultdict

        tmp = defaultdict(list)
        for row in rows:
            tmp[row.dataset_id].append(row.account_id)
        partial_member_map = dict(tmp)

    results = []
    for ds in datasets:
        partial_list = None
        if ds.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
            partial_list = partial_member_map.get(ds.id, [])
        results.append(DatasetOut(
            id=ds.id,
            tenant_id=ds.tenant_id,
            name=ds.name,
            description=ds.description,
            permission=ds.permission,
            owner_id=ds.owner_id,
            partial_member_list=partial_list
        ))
    return {"total": total, "items": results}


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(
    dataset_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)
    partial_list = None
    if dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
        partial_list = DatasetPermissionService.get_dataset_partial_member_list(db, tenant_id, dataset_id)
    return DatasetOut(
        id=dataset.id,
        tenant_id=dataset.tenant_id,
        name=dataset.name,
        description=dataset.description,
        permission=dataset.permission,
        owner_id=dataset.owner_id,
        partial_member_list=partial_list
    )


@router.patch("/{dataset_id}", response_model=DatasetOut)
def update_dataset(
    dataset_id: UUID,
    payload: DatasetUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    updated = DatasetService.update_dataset(
        db=db,
        dataset=dataset,
        updater_id=account_id,
        name=payload.name,
        description=payload.description,
        permission=payload.permission,
        partial_members=payload.partial_member_list,
    )
    partial_list = None
    if updated.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
        partial_list = DatasetPermissionService.get_dataset_partial_member_list(db, tenant_id, updated.id)

    return DatasetOut(
        id=updated.id,
        tenant_id=updated.tenant_id,
        name=updated.name,
        description=updated.description,
        permission=updated.permission,
        owner_id=updated.owner_id,
        partial_member_list=partial_list
    )


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)
    db.delete(dataset)
    db.commit()
    return None
