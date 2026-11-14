"""
Dataset Tables (TAG) API.

This provides a safe, SQL-first interface for structured table assets
that were ingested into the per-document table store.
"""

import hashlib
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.datasets import (
    DatasetTablesListResponse,
    LotusSemFilterRequest,
    TableAskRequest,
    TableAskResponse,
    TableAssetOut,
    TableColumnOut,
    TableQueryRequest,
    TableQueryResponse,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.rag.core.logging import get_logger
from app.rag.preprocessing.pii_anonymizer import anonymize_pii
from app.rag.preprocessing.secrets import redact_secrets
from app.services import dataset_service
from app.services.audit_log_service import audit_log_event
from app.services.document_access import filter_allowed_document_ids, get_allowed_document_id_sets
from app.services.fls_policy import (
    FlsPolicy,
    FlsUserContext,
    build_fls_column_mask_map,
    parse_fls_policy_from_metadata,
    redact_row_dicts,
    redact_row_lists,
)
from app.services.lotus_bridge import get_lotus_availability
from app.services.lotus_bridge import sem_filter as lotus_sem_filter
from app.services.rbac_service import TenantPermissions, role_allows
from app.services.security_redaction import redact_sql_literals
from app.services.table_store import (
    TableId,
    parse_table_id,
    quote_sqlite_ident,
    sql_table_name_for_sheet,
    table_store_path,
)
from app.services.table_store_service import run_table_query
from app.services.table_tag_service import (
    generate_answer_from_result,
    generate_sql_for_table,
    generate_sql_for_table_with_metadata,
)

if TYPE_CHECKING:
    import pandas as pd

logger = get_logger(__name__)


_DETAIL_INVALID_TABLE_ID = "invalid table_id"
_DETAIL_TABLE_NOT_FOUND = "table not found"

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _can_view_redacted_sql_role(role: str) -> bool:
    return role_allows(TenantPermissions.TABLE_SQL_READ, role=role)


def _should_redact_table_rows_role(role: str) -> bool:
    # Admin/auditor roles can view raw rows; others see best-effort redaction.
    return settings.TABLE_ROW_REDACTION_ENABLED and not _can_view_redacted_sql_role(role)


def _redact_table_text(text: str) -> str:
    secrets_mode = settings.GOVERNANCE_SECRETS_MODE.strip().lower()
    secrets_mode = secrets_mode if secrets_mode in {"mask", "token"} else "mask"
    redacted = redact_secrets(text, enabled=True, mode=secrets_mode, mask=settings.GOVERNANCE_SECRETS_MASK).text
    return anonymize_pii(
        redacted, enabled=True, mode=settings.GOVERNANCE_PII_MODE, mask=settings.GOVERNANCE_PII_MASK
    ).text


def _redact_table_cell(value: Any) -> Any:
    return _redact_table_text(value) if isinstance(value, str) else value


def _redact_table_rows(rows: list[list[Any]]) -> list[list[Any]]:
    return [[_redact_table_cell(value) for value in row] for row in rows]


def _redact_sample_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{str(key)[:500]: _redact_table_cell(value) for key, value in row.items()} for row in rows]


def _audit_table_query(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    table_id: str,
    sql: str,
) -> None:
    try:
        redacted_sql = redact_sql_literals(sql)
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="table.query",
            resource_type="dataset_table",
            resource_id=str(table_id),
            details={
                "dataset_id": str(dataset_id),
                "table_id": str(table_id),
                "sql_hash": hashlib.sha256(sql.encode("utf-8", "ignore")).hexdigest()[:16],
                "sql_chars": len(sql),
                "sql_redacted": redacted_sql,
            },
        )
        db.commit()
    except Exception:  # noqa: BLE001 - audit logging is a documented fail-open boundary
        db.rollback()
        logger.warning("Table query audit failed", exc_info=True)


def _audit_fls_redaction(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    source: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any],
) -> None:
    # Best-effort, fail-open: redaction enforcement must never block product flows.
    try:
        payload: dict[str, Any] = {
            "dataset_id": str(dataset_id),
            "source": source[:64],
            **details,
        }
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="fls.redaction_applied",
            resource_type=resource_type[:64],
            resource_id=resource_id[:255],
            details=payload,
        )
        db.commit()
    except Exception:  # noqa: BLE001 - FLS audit must not block redaction enforcement
        db.rollback()
        logger.warning("FLS redaction audit failed", exc_info=True)


def _table_member_context(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
) -> tuple[str, FlsPolicy | None, FlsUserContext]:
    dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
    dataset_service.assert_dataset_readable(db, dataset, account_id)
    member = dataset_service.ensure_member(db, tenant_id, account_id)
    role = member.role.strip().lower()
    fls_policy = parse_fls_policy_from_metadata(dataset.dataset_metadata or {})
    fls_ctx = FlsUserContext(account_id=account_id, role=role)
    return role, fls_policy, fls_ctx


def _require_table_id(db: Session, *, tenant_id: UUID, account_id: str, table_id: str) -> TableId:
    parsed = parse_table_id(table_id)
    if parsed is None:
        raise HTTPException(status_code=400, detail=_DETAIL_INVALID_TABLE_ID)
    filter_allowed_document_ids(db, tenant_id, account_id, [parsed.document_id])
    return parsed


def _table_columns_payload(table_meta: dict[str, Any], *, include_columns: bool) -> list[TableColumnOut]:
    if not include_columns:
        return []
    cols_payload: list[TableColumnOut] = []
    for column in table_meta.get("columns") or []:
        if not isinstance(column, dict):
            continue
        raw_name = column.get("name")
        if raw_name is None:
            continue
        name = raw_name.strip()
        if not name:
            continue
        cols_payload.append(
            TableColumnOut(
                name=name[:500],
                dtype=(str(column.get("dtype"))[:100] if column.get("dtype") is not None else None),
            )
        )
        if len(cols_payload) >= 2000:
            break
    return cols_payload


def _table_sample_rows_payload(
    table_meta: dict[str, Any],
    *,
    include_sample_rows: bool,
    redact_sample_rows: bool,
) -> list[dict[str, Any]]:
    if not include_sample_rows:
        return []
    sample_payload = [row for row in (table_meta.get("sample_rows") or []) if isinstance(row, dict)][:200]
    return _redact_sample_rows(sample_payload) if redact_sample_rows else sample_payload


def _table_asset_from_metadata(
    *,
    doc: DBDocument,
    parsed_table_id: TableId,
    table_meta: dict[str, Any],
    columns: list[TableColumnOut],
    sample_rows: list[dict[str, Any]],
) -> TableAssetOut:
    return TableAssetOut(
        table_id=table_meta["table_id"].strip(),
        document_id=doc.id,
        document_filename=doc.filename,
        sheet_index=int(table_meta.get("sheet_index") or parsed_table_id.sheet_index),
        sheet_name=(str(table_meta.get("sheet_name"))[:200] if table_meta.get("sheet_name") is not None else None),
        row_count=int(table_meta.get("row_count") or 0),
        col_count=int(table_meta.get("col_count") or 0),
        truncated=bool(table_meta.get("truncated") or False),
        columns=columns,
        sample_rows=sample_rows,
        row_source_table=(
            str(table_meta.get("row_source_table"))[:300] if table_meta.get("row_source_table") is not None else None
        ),
        row_source_sync_token=(
            str(table_meta.get("row_source_sync_token"))[:300]
            if table_meta.get("row_source_sync_token") is not None
            else None
        ),
        row_source_pk_hash_col=(
            str(table_meta.get("row_source_pk_hash_col"))[:120]
            if table_meta.get("row_source_pk_hash_col") is not None
            else None
        ),
    )


def _sample_row_columns(sample_rows: list[dict[str, Any]]) -> list[str]:
    seen_cols: set[str] = set()
    cols: list[str] = []
    for row in sample_rows:
        for name in row:
            if not name or name in seen_cols:
                continue
            seen_cols.add(name)
            cols.append(name)
            if len(cols) >= 2000:
                return cols
    return cols


def _mask_table_asset_sample_rows(
    item: TableAssetOut,
    *,
    fls_policy: FlsPolicy,
    fls_ctx: FlsUserContext,
) -> list[str]:
    sample_rows = item.sample_rows
    if not sample_rows:
        return []
    cols = _sample_row_columns(sample_rows)
    mask_map = build_fls_column_mask_map(fls_policy, source="table_store", columns=cols, ctx=fls_ctx)
    if not mask_map:
        return []
    item.sample_rows = redact_row_dicts(sample_rows, mask_map=mask_map)
    return list(mask_map)


def _mask_table_query_rows(
    payload: TableQueryResponse,
    *,
    fls_policy: FlsPolicy | None,
    fls_ctx: FlsUserContext,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    table_id: str,
) -> TableQueryResponse:
    if fls_policy is None:
        return payload
    mask_map = build_fls_column_mask_map(fls_policy, source="table_store", columns=payload.columns, ctx=fls_ctx)
    masked_cols = [column for column in payload.columns if column in mask_map]
    if not masked_cols or not payload.rows:
        return payload
    rows = redact_row_lists(payload.rows, columns=payload.columns, mask_map=mask_map)
    _audit_fls_redaction(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        source="table_store",
        resource_type="dataset_table",
        resource_id=str(table_id),
        details={
            "table_id": str(table_id),
            "columns": [str(c)[:500] for c in masked_cols][:50],
            "column_count": len(masked_cols),
        },
    )
    return payload.model_copy(update={"rows": rows})


def _load_table_document_or_404(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
) -> DBDocument:
    doc = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail=_DETAIL_TABLE_NOT_FOUND)
    return doc


def _table_schema_for_table_id(
    doc: DBDocument, *, table_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    meta = doc.doc_metadata or {}
    store = meta.get("table_store") if isinstance(meta, dict) else None
    tables = store.get("tables") if isinstance(store, dict) else None
    if not isinstance(tables, list):
        return [], [], None
    for table_meta in tables:
        if not isinstance(table_meta, dict):
            continue
        raw_table_id = table_meta.get("table_id")
        if raw_table_id is None or raw_table_id.strip() != table_id:
            continue
        columns = [c for c in (table_meta.get("columns") or []) if isinstance(c, dict)]
        sample_rows = [r for r in (table_meta.get("sample_rows") or []) if isinstance(r, dict)]
        sheet_name_raw = table_meta.get("sheet_name")
        sheet_name = str(sheet_name_raw).strip() if sheet_name_raw is not None else None
        return columns, sample_rows, sheet_name
    return [], [], None


def _maybe_redact_query_rows(payload: TableQueryResponse, *, redact_rows: bool) -> TableQueryResponse:
    if not redact_rows:
        return payload
    return payload.model_copy(update={"rows": _redact_table_rows(payload.rows)})


def _apply_table_assets_fls(
    items: list[TableAssetOut],
    *,
    fls_policy: FlsPolicy,
    fls_ctx: FlsUserContext,
) -> tuple[int, list[str], list[str]]:
    redacted_tables = 0
    redacted_table_ids: list[str] = []
    redacted_columns: set[str] = set()
    for item in items:
        present = _mask_table_asset_sample_rows(item, fls_policy=fls_policy, fls_ctx=fls_ctx)
        if not present:
            continue
        redacted_tables += 1
        if len(redacted_table_ids) < 20:
            redacted_table_ids.append(item.table_id[:255])
        for column in present:
            if len(redacted_columns) >= 50:
                break
            redacted_columns.add(str(column)[:500])
    return redacted_tables, redacted_table_ids, list(redacted_columns)


def _table_asset_by_id_or_404(
    assets: list[TableAssetOut],
    *,
    table_id: str,
) -> TableAssetOut:
    for asset in assets:
        if asset.table_id == table_id:
            return asset
    raise HTTPException(status_code=404, detail=_DETAIL_TABLE_NOT_FOUND)


def _lotus_select_query(conn: sqlite3.Connection, *, sql_table_q: str, max_in_rows: int, max_in_cols: int) -> str:
    cur = conn.execute(f"PRAGMA table_info({sql_table_q})")
    cols = [row[1] for row in cur.fetchall() if row[1].strip()][:max_in_cols]
    if not cols:
        return f"SELECT * FROM {sql_table_q} LIMIT {max_in_rows}"  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
    select_list = ", ".join(quote_sqlite_ident(column) for column in cols)
    return f"SELECT {select_list} FROM {sql_table_q} LIMIT {max_in_rows}"  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.


def _apply_lotus_dataframe_fls(df: "pd.DataFrame", *, fls_policy: FlsPolicy | None, fls_ctx: FlsUserContext) -> None:
    if fls_policy is None:
        return
    df_cols = [str(column) for column in df.columns]
    mask_map = build_fls_column_mask_map(fls_policy, source="table_store", columns=df_cols, ctx=fls_ctx)
    for column, mask in mask_map.items():
        df[column] = mask


def _load_lotus_dataframe(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
    sql_table_q: str,
    fls_policy: FlsPolicy | None,
    fls_ctx: FlsUserContext,
) -> "pd.DataFrame":
    import pandas as pd  # type: ignore

    max_in_rows = min(settings.TABLE_LOTUS_MAX_ROWS, settings.TABLE_SEM_FILTER_MAX_IN_ROWS, 100000)
    max_in_cols = settings.TABLE_SEM_FILTER_MAX_COLS
    db_path = table_store_path(tenant_id=tenant_id, dataset_id=dataset_id, document_id=document_id)
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)) as conn:
        query = _lotus_select_query(conn, sql_table_q=sql_table_q, max_in_rows=max_in_rows, max_in_cols=max_in_cols)
        df = pd.read_sql_query(query, conn)
        _apply_lotus_dataframe_fls(df, fls_policy=fls_policy, fls_ctx=fls_ctx)
        return df


def _lotus_filtered_response(
    filtered: "pd.DataFrame",
    *,
    sql_table: str,
    output_rows: int,
    redact_rows: bool,
    fls_policy: FlsPolicy | None,
    fls_ctx: FlsUserContext,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    table_id: str,
) -> TableQueryResponse:
    cols = [str(column) for column in filtered.columns]
    rows: list[list[Any]] = []
    truncated = False
    for index, row in enumerate(filtered.itertuples(index=False, name=None)):  # type: ignore[attr-defined]
        if index >= output_rows:
            truncated = True
            break
        rows.append(
            [value if value is None or isinstance(value, (str, int, float, bool)) else str(value) for value in row]
        )
    payload = TableQueryResponse(sql=f"LOTUS sem_filter({sql_table})", columns=cols, rows=rows, truncated=truncated)
    payload = _maybe_redact_query_rows(payload, redact_rows=redact_rows)
    payload = _mask_table_query_rows(
        payload,
        fls_policy=fls_policy,
        fls_ctx=fls_ctx,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        table_id=table_id,
    )
    return payload


def _extract_table_assets(
    *,
    doc: DBDocument,
    include_columns: bool,
    include_sample_rows: bool,
    redact_sample_rows: bool,
) -> list[TableAssetOut]:
    meta = doc.doc_metadata or {}
    if not isinstance(meta, dict):
        return []
    store = meta.get("table_store")
    if not isinstance(store, dict):
        return []
    tables = store.get("tables")
    if not isinstance(tables, list):
        return []

    out: list[TableAssetOut] = []
    for table_meta in tables:
        if not isinstance(table_meta, dict):
            continue
        raw_table_id = table_meta.get("table_id")
        if raw_table_id is None:
            continue
        table_id = raw_table_id.strip()
        parsed = parse_table_id(table_id)
        if parsed is None:
            continue
        if parsed.document_id != doc.id:
            # Defense-in-depth: ignore malformed/stale metadata that points to a different document.
            continue
        out.append(
            _table_asset_from_metadata(
                doc=doc,
                parsed_table_id=parsed,
                table_meta=table_meta,
                columns=_table_columns_payload(table_meta, include_columns=include_columns),
                sample_rows=_table_sample_rows_payload(
                    table_meta,
                    include_sample_rows=include_sample_rows,
                    redact_sample_rows=redact_sample_rows,
                ),
            )
        )
    return out


@router.get(
    "/{dataset_id}/tables",
    response_model=DatasetTablesListResponse,
    summary="List tables ingested into the structured table store for a dataset",
)
def list_dataset_tables(
    dataset_id: UUID,
    skip: Annotated[int, Query(ge=0, description="Document-level offset (not table-level)")] = 0,
    limit: Annotated[int, Query(ge=1, le=500, description="Document-level limit (not table-level)")] = 100,
    include_columns: Annotated[bool, Query(description="Include column schema in each item")] = False,
    include_sample_rows: Annotated[bool, Query(description="Include sample rows in each item")] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DatasetTablesListResponse:
    role, fls_policy, fls_ctx = _table_member_context(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
    )
    redact_rows = include_sample_rows and _should_redact_table_rows_role(role)

    q = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.status == "completed",
        )
        .order_by(DBDocument.updated_at.desc(), DBDocument.id.asc())
    )

    # Best-effort filter: only docs that *might* have table_store metadata.
    # - Table-like files: csv/xls/xlsx
    # - Mixed documents: docx may contain embedded tables imported as a sidecar.
    # - Parsed documents: pdf may emit tables imported as a sidecar from parsing output.
    q = q.filter(DBDocument.file_type.in_(["csv", "xlsx", "xls", "docx", "pdf", "dbrows"]))

    # Apply doc-level pagination first (table expansion happens after).
    docs = q.offset(skip).limit(limit).all()
    if not docs:
        return DatasetTablesListResponse(total=0, items=[])

    doc_ids = [d.id for d in docs]
    allowed_ids, _missing = get_allowed_document_id_sets(db, tenant_id, account_id, doc_ids, check_member=False)

    items: list[TableAssetOut] = []
    for d in docs:
        if d.id not in allowed_ids:
            continue
        items.extend(
            _extract_table_assets(
                doc=d,
                include_columns=include_columns,
                include_sample_rows=include_sample_rows,
                redact_sample_rows=redact_rows,
            )
        )

    # FLS: if sample rows are requested, mask values for denied columns (keep response shape).
    if include_sample_rows and fls_policy is not None and items:
        redacted_tables, redacted_table_ids, redacted_columns = _apply_table_assets_fls(
            items,
            fls_policy=fls_policy,
            fls_ctx=fls_ctx,
        )
        if redacted_tables > 0:
            _audit_fls_redaction(
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=dataset_id,
                source="table_store",
                resource_type="dataset",
                resource_id=str(dataset_id),
                details={
                    "table_count": redacted_tables,
                    "table_ids": redacted_table_ids,
                    "columns": redacted_columns,
                    "column_count": len(redacted_columns),
                },
            )

    return DatasetTablesListResponse(total=len(items), items=items)


@router.get(
    "/{dataset_id}/tables/{table_id}",
    response_model=TableAssetOut,
    summary="Get table metadata by table_id",
)
def get_dataset_table(
    dataset_id: UUID,
    table_id: str,
    include_columns: Annotated[bool, Query()] = True,
    include_sample_rows: Annotated[bool, Query()] = True,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TableAssetOut:
    role, fls_policy, fls_ctx = _table_member_context(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
    )
    redact_rows = include_sample_rows and _should_redact_table_rows_role(role)

    # Enforce document-level ACL and dataset binding.
    parsed = _require_table_id(db, tenant_id=tenant_id, account_id=account_id, table_id=table_id)
    doc = _load_table_document_or_404(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=parsed.document_id,
    )

    assets = _extract_table_assets(
        doc=doc,
        include_columns=include_columns,
        include_sample_rows=include_sample_rows,
        redact_sample_rows=redact_rows,
    )
    asset = _table_asset_by_id_or_404(assets, table_id=table_id)
    if include_sample_rows and fls_policy is not None:
        present = _mask_table_asset_sample_rows(asset, fls_policy=fls_policy, fls_ctx=fls_ctx)
        if present:
            _audit_fls_redaction(
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=dataset_id,
                source="table_store",
                resource_type="dataset_table",
                resource_id=str(table_id),
                details={
                    "table_id": str(table_id),
                    "columns": [str(column)[:500] for column in present][:50],
                    "column_count": len(present),
                },
            )
    return asset


@router.get(
    "/{dataset_id}/tables/{table_id}/preview",
    response_model=TableQueryResponse,
    summary="Preview a table (SELECT * ... LIMIT N)",
)
def preview_dataset_table(
    dataset_id: UUID,
    table_id: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TableQueryResponse:
    role, fls_policy, fls_ctx = _table_member_context(
        db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id
    )
    redact_rows = _should_redact_table_rows_role(role)
    parsed = _require_table_id(db, tenant_id=tenant_id, account_id=account_id, table_id=table_id)

    sql_table = sql_table_name_for_sheet(parsed.sheet_index)
    sql_table_q = quote_sqlite_ident(sql_table)
    payload = run_table_query(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        table_id=table_id,
        sql=f"SELECT * FROM {sql_table_q}",
        max_rows=min(limit, settings.TABLE_QUERY_MAX_ROWS),
        max_cols=settings.TABLE_QUERY_MAX_COLS,
        max_bytes=settings.TABLE_QUERY_MAX_BYTES,
    )
    payload = TableQueryResponse.model_validate(payload)
    payload = _maybe_redact_query_rows(payload, redact_rows=redact_rows)
    payload = _mask_table_query_rows(
        payload,
        fls_policy=fls_policy,
        fls_ctx=fls_ctx,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        table_id=table_id,
    )
    return payload


@router.post(
    "/{dataset_id}/tables/{table_id}/query",
    response_model=TableQueryResponse,
    summary="Run a SELECT-only SQL query against a table",
)
def query_dataset_table(
    dataset_id: UUID,
    table_id: str,
    body: TableQueryRequest,
    include_sql: Annotated[bool, Query(description="Include redacted SQL for owner/admin/auditor")] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TableQueryResponse:
    role, fls_policy, fls_ctx = _table_member_context(
        db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id
    )
    redact_rows = _should_redact_table_rows_role(role)
    _require_table_id(db, tenant_id=tenant_id, account_id=account_id, table_id=table_id)

    max_rows = body.max_rows or settings.TABLE_QUERY_MAX_ROWS
    max_cols = body.max_cols or settings.TABLE_QUERY_MAX_COLS

    payload = TableQueryResponse.model_validate(
        run_table_query(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            table_id=table_id,
            sql=body.sql,
            max_rows=min(max_rows, settings.TABLE_QUERY_MAX_ROWS),
            max_cols=min(max_cols, settings.TABLE_QUERY_MAX_COLS),
            max_bytes=settings.TABLE_QUERY_MAX_BYTES,
        )
    )
    raw_sql = payload.sql
    _audit_table_query(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        table_id=table_id,
        sql=raw_sql,
    )
    show_sql = include_sql and _can_view_redacted_sql_role(role)
    payload = _maybe_redact_query_rows(payload, redact_rows=redact_rows)
    payload = _mask_table_query_rows(
        payload,
        fls_policy=fls_policy,
        fls_ctx=fls_ctx,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        table_id=table_id,
    )
    payload.sql = redact_sql_literals(raw_sql) if show_sql else "<hidden>"
    return payload


@router.post(
    "/{dataset_id}/tables/{table_id}/ask",
    response_model=TableAskResponse,
    summary="TAG: Ask a question over a table (NL -> SQL -> execute -> answer)",
)
def ask_dataset_table(
    dataset_id: UUID,
    table_id: str,
    body: TableAskRequest,
    include_sql: Annotated[bool, Query(description="Include redacted SQL for owner/admin/auditor")] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TableAskResponse:
    if not settings.TABLE_NL2SQL_ENABLED:
        raise HTTPException(status_code=400, detail="TABLE_NL2SQL_ENABLED=false")
    deterministic_enabled = (
        settings.TABLE_NL2SQL_DETERMINISTIC_ONLY or settings.TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED
    )
    if not settings.LLM_API_KEY.strip() and not deterministic_enabled:
        raise HTTPException(status_code=400, detail="LLM_API_KEY is not configured")

    role, fls_policy, fls_ctx = _table_member_context(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
    )
    redact_rows = _should_redact_table_rows_role(role)

    parsed = _require_table_id(db, tenant_id=tenant_id, account_id=account_id, table_id=table_id)
    doc = _load_table_document_or_404(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=parsed.document_id,
    )
    columns, sample_rows, sheet_name = _table_schema_for_table_id(doc, table_id=table_id)

    sql_table = sql_table_name_for_sheet(parsed.sheet_index)
    max_rows = body.max_rows or settings.TABLE_QUERY_MAX_ROWS
    max_rows = min(max_rows, settings.TABLE_QUERY_MAX_ROWS)

    try:
        sql, sql_generation_mode, sql_metadata = generate_sql_for_table_with_metadata(
            question=body.question,
            sql_table=sql_table,
            columns=columns,
            max_rows=max_rows,
            sample_rows=sample_rows,
            table_aliases=[table_id, doc.filename] + ([sheet_name] if sheet_name is not None else []),
        )
    except Exception as exc:  # noqa: BLE001 - preserve the API's provider failure response
        raise HTTPException(status_code=400, detail=f"nl2sql_failed: {str(exc)[:200]}") from exc
    if not sql.strip():
        raise HTTPException(status_code=400, detail="nl2sql_failed: empty sql")
    planner_diagnostics = sql_metadata["planner"]
    sql_fingerprint = sql_metadata["sql_fingerprint"]

    result = run_table_query(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        table_id=table_id,
        sql=sql,
        max_rows=max_rows,
        max_cols=settings.TABLE_QUERY_MAX_COLS,
        max_bytes=settings.TABLE_QUERY_MAX_BYTES,
        planner_diagnostics=planner_diagnostics,
        expected_sql_fingerprint=sql_fingerprint,
    )
    planner_execution_mismatch = result["planner_execution_mismatch"]
    if settings.TABLE_TAG_PLANNER_MISMATCH_STRICT and planner_execution_mismatch["mismatch"]:
        raise HTTPException(status_code=409, detail="planner_execution_mismatch")
    if not settings.TABLE_LLM_ALLOW_RESULT_EGRESS:
        raise HTTPException(
            status_code=400,
            detail="TABLE_LLM_ALLOW_RESULT_EGRESS=false (answer drafting requires sending query results to an LLM)",
        )

    # FLS: redact denied columns before any LLM call.
    data_payload = _mask_table_query_rows(
        TableQueryResponse.model_validate(result),
        fls_policy=fls_policy,
        fls_ctx=fls_ctx,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        table_id=table_id,
    )
    try:
        answer = generate_answer_from_result(
            question=body.question, sql=data_payload.sql, result=data_payload.model_dump()
        )
    except Exception as exc:  # noqa: BLE001 - preserve the API's provider failure response
        raise HTTPException(status_code=400, detail=f"answer_failed: {str(exc)[:200]}") from exc

    raw_sql = result["sql"]
    _audit_table_query(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        table_id=table_id,
        sql=raw_sql,
    )
    show_sql = include_sql and _can_view_redacted_sql_role(role)
    redacted_sql = redact_sql_literals(raw_sql) if show_sql else None
    data_payload = _maybe_redact_query_rows(data_payload, redact_rows=redact_rows)
    data_payload.sql = redacted_sql or "<hidden>"
    return TableAskResponse(
        answer=answer,
        sql=redacted_sql,
        data=data_payload,
        sql_generation_mode=sql_generation_mode,
        schema_link_diagnostics=sql_metadata["schema_link"],
        planner_diagnostics=planner_diagnostics,
        sql_fingerprint=sql_fingerprint,
        planner_execution_mismatch=planner_execution_mismatch,
    )


@router.post(
    "/{dataset_id}/tables/{table_id}/lotus/sem-filter",
    response_model=TableQueryResponse,
    summary="LOTUS (optional): semantic filter over a table (falls back to NL->SQL when LOTUS unavailable)",
)
def lotus_sem_filter_dataset_table(
    dataset_id: UUID,
    table_id: str,
    body: LotusSemFilterRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TableQueryResponse:
    if not settings.TABLE_LOTUS_ENABLED:
        raise HTTPException(status_code=400, detail="TABLE_LOTUS_ENABLED=false")
    if not settings.LLM_API_KEY.strip():
        raise HTTPException(status_code=400, detail="LLM_API_KEY is not configured")

    role, fls_policy, fls_ctx = _table_member_context(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
    )
    redact_rows = _should_redact_table_rows_role(role)

    parsed = _require_table_id(db, tenant_id=tenant_id, account_id=account_id, table_id=table_id)
    _load_table_document_or_404(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=parsed.document_id,
    )

    sql_table = sql_table_name_for_sheet(parsed.sheet_index)
    sql_table_q = quote_sqlite_ident(sql_table)
    output_rows = body.max_rows or settings.TABLE_QUERY_MAX_ROWS
    output_rows = min(output_rows, settings.TABLE_QUERY_MAX_ROWS)

    availability = get_lotus_availability()
    unavailable_reason = availability.reason
    if availability.ok:
        try:
            df = _load_lotus_dataframe(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=parsed.document_id,
                sql_table_q=sql_table_q,
                fls_policy=fls_policy,
                fls_ctx=fls_ctx,
            )
            filtered = lotus_sem_filter(
                df,
                user_instruction=body.user_instruction,
            )
        except Exception as exc:  # noqa: BLE001
            unavailable_reason = f"lotus failed: {str(exc)[:200]}"
            logger.warning(
                "LOTUS semantic filter failed: tenant_id=%s dataset_id=%s error_type=%s",
                tenant_id,
                dataset_id,
                type(exc).__name__,
            )
        else:
            return _lotus_filtered_response(
                filtered,
                sql_table=sql_table,
                output_rows=output_rows,
                redact_rows=redact_rows,
                fls_policy=fls_policy,
                fls_ctx=fls_ctx,
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=dataset_id,
                table_id=table_id,
            )

    # Fallback: use NL->SQL to generate a WHERE clause and execute safely.
    if not settings.TABLE_NL2SQL_ENABLED:
        raise HTTPException(
            status_code=400,
            detail=f"LOTUS unavailable: {unavailable_reason} (and TABLE_NL2SQL_ENABLED=false)",
        )
    try:
        sql = generate_sql_for_table(
            question=f"Filter rows that match: {body.user_instruction.strip()}. Return the matching rows.",
            sql_table=sql_table,
            columns=[],
            max_rows=output_rows,
        )
    except Exception as exc:  # noqa: BLE001 - preserve the API's provider failure response
        raise HTTPException(status_code=400, detail=f"nl2sql_failed: {str(exc)[:200]}") from exc
    payload = TableQueryResponse.model_validate(
        run_table_query(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            table_id=table_id,
            sql=sql,
            max_rows=output_rows,
            max_cols=settings.TABLE_QUERY_MAX_COLS,
            max_bytes=settings.TABLE_QUERY_MAX_BYTES,
        )
    )
    payload = _maybe_redact_query_rows(payload, redact_rows=redact_rows)
    return _mask_table_query_rows(
        payload,
        fls_policy=fls_policy,
        fls_ctx=fls_ctx,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        table_id=table_id,
    )
