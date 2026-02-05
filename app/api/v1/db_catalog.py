"""
DB catalog (SQLServer/MySQL) read APIs.

These endpoints expose metadata and safe, aggregate profiling snapshots stored
by DB catalog connectors. They do NOT expose raw DB rows.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.db_catalog import (
    DbCatalogColumnOut,
    DbCatalogTableDetailOut,
    DbCatalogTablesListResponse,
    DbCatalogTableSummaryOut,
    DbProfileSnapshotListResponse,
    DbProfileSnapshotOut,
)
from app.core.database import get_db
from app.models.db_catalog import DbCatalogColumn, DbCatalogTable, DbProfileSnapshot
from app.services.dataset_service import DatasetService

router = APIRouter()


@router.get(
    "/{dataset_id}/db-catalog/tables",
    response_model=DbCatalogTablesListResponse,
    summary="List DB catalog tables/views for a dataset",
)
def list_db_catalog_tables(
    dataset_id: UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    engine: Optional[str] = Query(default=None, description="Filter by engine: mysql|sqlserver"),
    q: Optional[str] = Query(default=None, description="Fuzzy search across db/schema/table names"),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    query = db.query(DbCatalogTable).filter(DbCatalogTable.tenant_id == tenant_id, DbCatalogTable.dataset_id == dataset_id)

    eng = str(engine or "").strip().lower()
    if eng:
        if eng not in {"mysql", "sqlserver"}:
            raise HTTPException(status_code=400, detail="invalid engine")
        query = query.filter(DbCatalogTable.engine == eng)

    needle = str(q or "").strip()
    if needle:
        needle = needle[:200]
        like = f"%{needle}%"
        query = query.filter(
            or_(
                DbCatalogTable.table_name.ilike(like),
                DbCatalogTable.schema_name.ilike(like),
                DbCatalogTable.db_name.ilike(like),
            )
        )

    total = int(query.count())
    rows = (
        query.order_by(DbCatalogTable.updated_at.desc(), DbCatalogTable.id.asc())
        .offset(int(skip))
        .limit(int(limit))
        .all()
    )

    items = [DbCatalogTableSummaryOut.model_validate(r) for r in rows]
    return DbCatalogTablesListResponse(total=total, items=items)


@router.get(
    "/{dataset_id}/db-catalog/tables/{table_id}",
    response_model=DbCatalogTableDetailOut,
    summary="Get DB catalog table/view detail (includes columns)",
)
def get_db_catalog_table(
    dataset_id: UUID,
    table_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    table = (
        db.query(DbCatalogTable)
        .filter(
            DbCatalogTable.id == table_id,
            DbCatalogTable.tenant_id == tenant_id,
            DbCatalogTable.dataset_id == dataset_id,
        )
        .first()
    )
    if table is None:
        raise HTTPException(status_code=404, detail="table not found")

    cols = (
        db.query(DbCatalogColumn)
        .filter(DbCatalogColumn.table_id == table.id)
        .order_by(DbCatalogColumn.ordinal.asc(), DbCatalogColumn.name.asc(), DbCatalogColumn.id.asc())
        .all()
    )

    base = DbCatalogTableSummaryOut.model_validate(table).model_dump()
    return DbCatalogTableDetailOut(**base, columns=[DbCatalogColumnOut.model_validate(c) for c in cols])


@router.get(
    "/{dataset_id}/db-catalog/profiles",
    response_model=DbProfileSnapshotListResponse,
    summary="List safe profile snapshots for a catalog table",
)
def list_db_catalog_profiles(
    dataset_id: UUID,
    table_id: UUID = Query(..., description="Catalog table id"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    # Defense-in-depth: ensure table belongs to dataset/tenant before returning snapshots.
    exists = (
        db.query(DbCatalogTable.id)
        .filter(DbCatalogTable.id == table_id, DbCatalogTable.tenant_id == tenant_id, DbCatalogTable.dataset_id == dataset_id)
        .first()
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="table not found")

    query = db.query(DbProfileSnapshot).filter(DbProfileSnapshot.table_id == table_id)
    total = int(query.count())
    rows = query.order_by(DbProfileSnapshot.created_at.desc(), DbProfileSnapshot.id.asc()).offset(int(skip)).limit(int(limit)).all()

    items = [DbProfileSnapshotOut.model_validate(r) for r in rows]
    return DbProfileSnapshotListResponse(total=total, items=items)

