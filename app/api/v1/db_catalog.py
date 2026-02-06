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

from app.connectors.db.profile_privacy import sanitize_db_profile_snapshot
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
from app.services.db_catalog_profile_cache import (
    build_db_profile_cache_key,
    get_cached_db_profile,
    set_cached_db_profile,
)

router = APIRouter()

_DB_PROFILE_VERSION = 1
_DB_PROFILE_CACHE_TTL_SEC = 30.0


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
    entitlement_hash: Optional[str] = Query(default=None, description="Filter by entitlement hash (stable permission context)"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    # Defense-in-depth: ensure table belongs to dataset/tenant before returning snapshots.
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

    ent = str(entitlement_hash or "").strip()
    if ent:
        ent = ent[:255]

    # Cache: common UI path fetches the latest snapshot repeatedly while browsing tables.
    use_cache = int(skip or 0) == 0 and int(limit or 0) == 1
    cache_key = None
    if use_cache:
        cache_key = build_db_profile_cache_key(
            tenant_id=str(tenant_id),
            dataset_id=str(dataset_id),
            entitlement_hash=(ent or "any"),
            table_fingerprint=str(getattr(table, "fingerprint", "") or ""),
            profile_version=_DB_PROFILE_VERSION,
        )
        cached = get_cached_db_profile(cache_key, ttl_sec=_DB_PROFILE_CACHE_TTL_SEC)
        if isinstance(cached, dict):
            return DbProfileSnapshotListResponse.model_validate(cached)

    query = db.query(DbProfileSnapshot).filter(DbProfileSnapshot.table_id == table_id)
    if ent:
        query = query.filter(DbProfileSnapshot.entitlement_hash == ent)
    total = int(query.count())
    rows = query.order_by(DbProfileSnapshot.created_at.desc(), DbProfileSnapshot.id.asc()).offset(int(skip)).limit(int(limit)).all()

    items: list[DbProfileSnapshotOut] = []
    for r in rows:
        out = DbProfileSnapshotOut.model_validate(r)
        # Defense-in-depth: sanitize on read in case older snapshots were stored before guards existed.
        out.profile = sanitize_db_profile_snapshot(out.profile)
        items.append(out)

    resp = DbProfileSnapshotListResponse(total=total, items=items)
    if cache_key is not None:
        set_cached_db_profile(cache_key, resp.model_dump(mode="json"))
    return resp
