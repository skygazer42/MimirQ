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

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.datasets import (
    DbCatalogColumnOut,
    DbCatalogTableDetailOut,
    DbCatalogTablesListResponse,
    DbCatalogTableSummaryOut,
    DbProfileSnapshotListResponse,
    DbProfileSnapshotOut,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.connectors.profile_privacy import sanitize_db_profile_snapshot
from app.core.database import get_db
from app.models.db_catalog import DbCatalogColumn, DbCatalogTable, DbProfileSnapshot
from app.rag.core.logging import get_logger
from app.services import dataset_service
from app.services.audit_log_service import audit_log_event
from app.services.db_catalog_profile_cache import (
    build_db_profile_cache_key,
    get_cached_db_profile,
    set_cached_db_profile,
)
from app.services.fls_policy import FlsUserContext, build_fls_column_mask_map, parse_fls_policy_from_metadata

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)

_DB_PROFILE_VERSION = 1
_DB_PROFILE_CACHE_TTL_SEC = 30.0
logger = get_logger(__name__)


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
        cols = [column[:500] for column in redacted_columns if column.strip()][:50]
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
                "column_count": len(cols),
            },
        )
        db.commit()
    except Exception:  # noqa: BLE001 - audit logging is a documented fail-open boundary
        db.rollback()
        logger.warning("DB catalog redaction audit failed", exc_info=True)


def _require_db_catalog_table(db: Session, *, tenant_id: UUID, dataset_id: UUID, table_id: UUID) -> DbCatalogTable:
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
    return table


@router.get(
    "/{dataset_id}/db-catalog/tables",
    response_model=DbCatalogTablesListResponse,
    summary="List DB catalog tables/views for a dataset",
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
) -> DbCatalogTablesListResponse:
    dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
    dataset_service.assert_dataset_readable(db, dataset, account_id)

    query = db.query(DbCatalogTable).filter(
        DbCatalogTable.tenant_id == tenant_id, DbCatalogTable.dataset_id == dataset_id
    )

    normalized_engine = engine.strip().lower() if engine is not None else None
    if normalized_engine:
        if normalized_engine not in {"mysql", "sqlserver"}:
            raise HTTPException(status_code=400, detail="invalid engine")
        query = query.filter(DbCatalogTable.engine == normalized_engine)

    needle = q.strip() if q is not None else None
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

    total = query.count()
    rows = query.order_by(DbCatalogTable.updated_at.desc(), DbCatalogTable.id.asc()).offset(skip).limit(limit).all()

    items = [DbCatalogTableSummaryOut.model_validate(row) for row in rows]
    return DbCatalogTablesListResponse(total=total, items=items)


@router.get(
    "/{dataset_id}/db-catalog/tables/{table_id}",
    response_model=DbCatalogTableDetailOut,
    summary="Get DB catalog table/view detail (includes columns)",
)
def get_db_catalog_table(
    dataset_id: UUID,
    table_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DbCatalogTableDetailOut:
    dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
    dataset_service.assert_dataset_readable(db, dataset, account_id)

    member = dataset_service.ensure_member(db, tenant_id, account_id)
    role = member.role.strip().lower()
    fls_policy = parse_fls_policy_from_metadata(dataset.dataset_metadata or {})
    fls_ctx = FlsUserContext(account_id=account_id, role=role)

    table = _require_db_catalog_table(db, tenant_id=tenant_id, dataset_id=dataset_id, table_id=table_id)

    columns = (
        db.query(DbCatalogColumn)
        .filter(DbCatalogColumn.table_id == table.id)
        .order_by(DbCatalogColumn.ordinal.asc(), DbCatalogColumn.name.asc(), DbCatalogColumn.id.asc())
        .all()
    )

    table_values = DbCatalogTableSummaryOut.model_validate(table).model_dump()
    output_columns: list[DbCatalogColumnOut] = []
    redacted_columns: list[str] = []
    mask_map = build_fls_column_mask_map(
        fls_policy, source="db_catalog", columns=[column.name for column in columns], ctx=fls_ctx
    )

    for column in columns:
        output_column = DbCatalogColumnOut.model_validate(column)
        mask = mask_map.get(column.name)
        if mask:
            redacted_columns.append(column.name)
            output_column = output_column.model_copy(update={"name": mask, "comment": mask})
        output_columns.append(output_column)

    if redacted_columns:
        _audit_fls_redaction(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            table_id=table_id,
            redacted_columns=redacted_columns,
        )

    return DbCatalogTableDetailOut(**table_values, columns=output_columns)


@router.get(
    "/{dataset_id}/db-catalog/profiles",
    response_model=DbProfileSnapshotListResponse,
    summary="List safe profile snapshots for a catalog table",
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
) -> DbProfileSnapshotListResponse:
    dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
    dataset_service.assert_dataset_readable(db, dataset, account_id)

    table = _require_db_catalog_table(db, tenant_id=tenant_id, dataset_id=dataset_id, table_id=table_id)

    ent = entitlement_hash.strip() if entitlement_hash is not None else None
    if ent:
        ent = ent[:255]

    # Cache: common UI path fetches the latest snapshot repeatedly while browsing tables.
    cache_key = None
    if skip == 0 and limit == 1:
        cache_key = build_db_profile_cache_key(
            tenant_id=str(tenant_id),
            dataset_id=str(dataset_id),
            entitlement_hash=(ent or "any"),
            table_fingerprint=table.fingerprint,
            profile_version=_DB_PROFILE_VERSION,
        )
        cached = get_cached_db_profile(cache_key, ttl_sec=_DB_PROFILE_CACHE_TTL_SEC)
        if cached is not None:
            return DbProfileSnapshotListResponse.model_validate(cached)

    query = db.query(DbProfileSnapshot).filter(DbProfileSnapshot.table_id == table_id)
    if ent:
        query = query.filter(DbProfileSnapshot.entitlement_hash == ent)
    total = query.count()
    rows = (
        query.order_by(DbProfileSnapshot.created_at.desc(), DbProfileSnapshot.id.asc()).offset(skip).limit(limit).all()
    )

    items: list[DbProfileSnapshotOut] = []
    for row in rows:
        out = DbProfileSnapshotOut.model_validate(row)
        # Defense-in-depth: sanitize on read in case older snapshots were stored before guards existed.
        out.profile = sanitize_db_profile_snapshot(out.profile)
        items.append(out)

    resp = DbProfileSnapshotListResponse(total=total, items=items)
    if cache_key is not None:
        set_cached_db_profile(cache_key, resp.model_dump(mode="json"))
    return resp
