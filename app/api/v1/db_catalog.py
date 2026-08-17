"""
DB catalog (SQLServer/MySQL) read APIs.

These endpoints expose metadata and safe, aggregate profiling snapshots stored
by DB catalog connectors. They do NOT expose raw DB rows.
"""

from typing import Annotated
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
from app.connectors.db.profile_privacy import sanitize_db_profile_snapshot
from app.core.database import get_db
from app.models.db_catalog import DbCatalogColumn, DbCatalogTable, DbProfileSnapshot
from app.services.audit_log_service import audit_log_event
from app.services.dataset_service import DatasetService
from app.services.db_catalog_profile_cache import (
    build_db_profile_cache_key,
    get_cached_db_profile,
    set_cached_db_profile,
)
from app.services.fls_policy import FlsUserContext, build_fls_column_mask_map, parse_fls_policy_from_metadata

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_DB_PROFILE_VERSION = 1
_DB_PROFILE_CACHE_TTL_SEC = 30.0


def _audit_fls_redaction(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    table_id: UUID,
    redacted_columns: list[str],
) -> None:
    try:
        cols = [str(c)[:500] for c in (redacted_columns or []) if str(c or "").strip()][:50]
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="fls.redaction_applied",
            resource_type="db_catalog_table",
            resource_id=str(table_id),
            details={
                "dataset_id": str(dataset_id),
                "source": "db_catalog",
                "table_id": str(table_id),
                "columns": cols,
                "column_count": int(len(cols)),
            },
        )
    except Exception:
        return
    try:
        db.commit()
    except Exception:
        return


@router.get(
    "/{dataset_id}/db-catalog/tables",
    response_model=DbCatalogTablesListResponse,
    summary="List DB catalog tables/views for a dataset",
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def list_db_catalog_tables(
    dataset_id: UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    engine: Annotated[str | None, Query(description="Filter by engine: mysql|sqlserver")] = None,
    q: Annotated[str | None, Query(description="Fuzzy search across db/schema/table names")] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    query = db.query(DbCatalogTable).filter(
        DbCatalogTable.tenant_id == tenant_id, DbCatalogTable.dataset_id == dataset_id
    )

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
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_db_catalog_table(
    dataset_id: UUID,
    table_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = str(getattr(member, "role", "") or "").strip().lower()
    fls_policy = parse_fls_policy_from_metadata(getattr(dataset, "dataset_metadata", None) or {})
    fls_ctx = FlsUserContext(account_id=account_id, role=role)

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
    out_cols: list[DbCatalogColumnOut] = []
    redacted: list[str] = []
    if fls_policy is not None and cols:
        mask_map = build_fls_column_mask_map(
            fls_policy,
            source="db_catalog",
            columns=[str(getattr(c, "name", "") or "") for c in cols],
            ctx=fls_ctx,
        )
    else:
        mask_map = {}

    for c in cols:
        out = DbCatalogColumnOut.model_validate(c)
        mask = mask_map.get(str(getattr(c, "name", "") or ""))
        if mask:
            redacted.append(str(getattr(c, "name", "") or ""))
            out = out.model_copy(update={"name": str(mask), "comment": str(mask)})
        out_cols.append(out)

    if redacted:
        _audit_fls_redaction(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            table_id=table_id,
            redacted_columns=redacted,
        )

    return DbCatalogTableDetailOut(**base, columns=out_cols)


@router.get(
    "/{dataset_id}/db-catalog/profiles",
    response_model=DbProfileSnapshotListResponse,
    summary="List safe profile snapshots for a catalog table",
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def list_db_catalog_profiles(
    dataset_id: UUID,
    table_id: Annotated[UUID, Query(..., description="Catalog table id")],
    entitlement_hash: Annotated[
        str | None, Query(description="Filter by entitlement hash (stable permission context)")
    ] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
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
    rows = (
        query.order_by(DbProfileSnapshot.created_at.desc(), DbProfileSnapshot.id.asc())
        .offset(int(skip))
        .limit(int(limit))
        .all()
    )

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
