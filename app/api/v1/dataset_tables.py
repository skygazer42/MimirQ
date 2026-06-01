"""
Dataset Tables (TAG) API.

This provides a safe, SQL-first interface for structured table assets
that were ingested into the per-document table store.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.table_store import (
    DatasetTablesListResponse,
    LotusSemFilterRequest,
    TableAskRequest,
    TableAskResponse,
    TableAssetOut,
    TableColumnOut,
    TableQueryRequest,
    TableQueryResponse,
)
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.rag.core.logging import get_logger
from app.rag.preprocessing.pii_anonymizer import anonymize_pii
from app.rag.preprocessing.secrets import redact_secrets
from app.services.audit_log_service import audit_log_event
from app.services.dataset_service import DatasetService
from app.services.document_access import filter_allowed_document_ids, get_allowed_document_id_sets
from app.services.fls_policy import (
    FlsUserContext,
    build_fls_column_mask_map,
    parse_fls_policy_from_metadata,
    redact_row_dicts,
    redact_row_lists,
)
from app.services.lotus_bridge import lotus_available
from app.services.lotus_bridge import sem_filter as lotus_sem_filter
from app.services.rbac_service import TenantPermissions, role_allows
from app.services.security_redaction import redact_sql_literals
from app.services.table_sql_fingerprint import fingerprint_sql
from app.services.table_store import parse_table_id, quote_sqlite_ident, sql_table_name_for_sheet, table_store_path
from app.services.table_store_service import run_table_query
from app.services.table_tag_service import (
    generate_answer_from_result,
    generate_sql_for_table,
    generate_sql_for_table_with_metadata,
    tag_enabled,
)

logger = get_logger(__name__)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

_DETAIL_INVALID_TABLE_ID = "invalid table_id"
_DETAIL_TABLE_NOT_FOUND = "table not found"

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _member_role(member: object) -> str:
    return str(getattr(member, "role", "") or "").strip().lower()


def _can_view_redacted_sql_role(role: str) -> bool:
    return role_allows(TenantPermissions.TABLE_SQL_READ, role=role)


def _should_redact_table_rows_role(role: str) -> bool:
    if not bool(getattr(settings, "TABLE_ROW_REDACTION_ENABLED", False)):
        return False
    # Admin/auditor roles can view raw rows; others see best-effort redaction.
    return not _can_view_redacted_sql_role(role)


def _can_view_redacted_sql(db: Session, tenant_id: UUID, account_id: str) -> bool:
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    return _can_view_redacted_sql_role(_member_role(member))


def _should_redact_table_rows(db: Session, tenant_id: UUID, account_id: str) -> bool:
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    return _should_redact_table_rows_role(_member_role(member))


def _redact_table_text(text: str) -> str:
    s = text or ""
    if not s:
        return s

    secrets_mode = str(getattr(settings, "GOVERNANCE_SECRETS_MODE", "mask") or "mask").strip().lower()
    secrets_mask = str(getattr(settings, "GOVERNANCE_SECRETS_MASK", "[SECRET]") or "[SECRET]")
    pii_mode = str(getattr(settings, "GOVERNANCE_PII_MODE", "mask") or "mask").strip().lower()
    pii_mask = str(getattr(settings, "GOVERNANCE_PII_MASK", "[REDACTED]") or "[REDACTED]")

    secrets_mode = secrets_mode if secrets_mode in {"mask", "token"} else "mask"
    pii_mode = pii_mode if pii_mode in {"mask", "token"} else "mask"

    s = redact_secrets(s, enabled=True, mode=secrets_mode, mask=secrets_mask).text
    s = anonymize_pii(s, enabled=True, mode=pii_mode, mask=pii_mask).text
    return s


def _redact_table_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return _redact_table_text(value)
    return value


def _redact_table_rows(rows: list[list[Any]]) -> list[list[Any]]:
    out: list[list[Any]] = []
    for row in rows or []:
        if isinstance(row, tuple):
            row = list(row)
        if not isinstance(row, list):
            continue
        out.append([_redact_table_cell(v) for v in row])
    return out


def _redact_sample_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        redacted: dict[str, Any] = {}
        for k, v in r.items():
            key = str(k)[:500]
            redacted[key] = _redact_table_cell(v)
        out.append(redacted)
    return out


def _short_sql_hash(sql: str) -> str:
    raw = (sql or "").encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:16]


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
                "sql_hash": _short_sql_hash(sql),
                "sql_chars": len(str(sql or "")),
                "sql_redacted": redacted_sql,
            },
        )
    except Exception:
        return
    try:
        db.commit()
    except Exception:
        return


def _audit_fls_redaction(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    source: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    # Best-effort, fail-open: redaction enforcement must never block product flows.
    try:
        payload: dict[str, Any] = {
            "dataset_id": str(dataset_id),
            "source": str(source or "")[:64],
        }
        payload.update(dict(details or {}))
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="fls.redaction_applied",
            resource_type=str(resource_type or "")[:64] if resource_type else None,
            resource_id=str(resource_id or "")[:255] if resource_id else None,
            details=payload,
        )
    except Exception as exc:
        logger.debug("Ignoring FLS redaction audit write failure: %s", exc)
        return
    try:
        db.commit()
    except Exception as exc:
        logger.debug("Ignoring FLS redaction audit commit failure: %s", exc)
        return


def _extract_table_assets(
    *,
    doc: DBDocument,
    include_columns: bool,
    include_sample_rows: bool,
    redact_sample_rows: bool,
) -> list[TableAssetOut]:
    meta = getattr(doc, "doc_metadata", None) or {}
    if not isinstance(meta, dict):
        return []
    store = meta.get("table_store")
    if not isinstance(store, dict):
        return []
    tables = store.get("tables")
    if not isinstance(tables, list):
        return []

    out: list[TableAssetOut] = []
    for t in tables:
        if not isinstance(t, dict):
            continue
        table_id = str(t.get("table_id") or "").strip()
        parsed = parse_table_id(table_id)
        if parsed is None:
            continue
        if parsed.document_id != doc.id:
            # Defense-in-depth: ignore malformed/stale metadata that points to a different document.
            continue
        cols_payload = []
        if include_columns:
            for c in (t.get("columns") or []):
                if not isinstance(c, dict):
                    continue
                name = str(c.get("name") or "").strip()
                if not name:
                    continue
                cols_payload.append(TableColumnOut(name=name[:500], dtype=(str(c.get("dtype"))[:100] if c.get("dtype") is not None else None)))
                if len(cols_payload) >= 2000:
                    break

        sample_payload: list[dict[str, Any]] = []
        if include_sample_rows:
            for r in (t.get("sample_rows") or []):
                if isinstance(r, dict):
                    sample_payload.append(r)
                if len(sample_payload) >= 200:
                    break
            if redact_sample_rows:
                sample_payload = _redact_sample_rows(sample_payload)

        out.append(
            TableAssetOut(
                table_id=table_id,
                document_id=doc.id,
                document_filename=getattr(doc, "filename", None),
                sheet_index=int(t.get("sheet_index") or parsed.sheet_index),
                sheet_name=(str(t.get("sheet_name"))[:200] if t.get("sheet_name") is not None else None),
                row_count=int(t.get("row_count") or 0),
                col_count=int(t.get("col_count") or 0),
                truncated=bool(t.get("truncated") or False),
                columns=cols_payload,
                sample_rows=sample_payload,
                row_source_table=(str(t.get("row_source_table"))[:300] if t.get("row_source_table") is not None else None),
                row_source_sync_token=(
                    str(t.get("row_source_sync_token"))[:300] if t.get("row_source_sync_token") is not None else None
                ),
                row_source_pk_hash_col=(
                    str(t.get("row_source_pk_hash_col"))[:120] if t.get("row_source_pk_hash_col") is not None else None
                ),
            )
        )
    return out


@router.get(
    "/{dataset_id}/tables",
    response_model=DatasetTablesListResponse,
    summary="List tables ingested into the structured table store for a dataset",
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def list_dataset_tables(
    dataset_id: UUID,
    skip: Annotated[int, Query(ge=0, description='Document-level offset (not table-level)')] = 0,
    limit: Annotated[int, Query(ge=1, le=500, description='Document-level limit (not table-level)')] = 100,
    include_columns: Annotated[bool, Query(description='Include column schema in each item')] = False,
    include_sample_rows: Annotated[bool, Query(description='Include sample rows in each item')] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = _member_role(member)
    redact_rows = bool(include_sample_rows) and _should_redact_table_rows_role(role)

    fls_policy = parse_fls_policy_from_metadata(getattr(dataset, "dataset_metadata", None) or {})
    fls_ctx = FlsUserContext(account_id=account_id, role=role)

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
    docs = q.offset(int(skip)).limit(int(limit)).all()
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
    fls_redacted_tables = 0
    fls_redacted_table_ids: list[str] = []
    fls_redacted_columns: set[str] = set()
    if bool(include_sample_rows) and fls_policy is not None and items:
        for item in items:
            sample_rows = list(getattr(item, "sample_rows", None) or [])
            if not sample_rows:
                continue

            # Build a bounded, stable column list from sample row keys.
            seen_cols: set[str] = set()
            cols: list[str] = []
            for r in sample_rows:
                if not isinstance(r, dict):
                    continue
                for k in r.keys():
                    name = str(k or "")
                    if not name or name in seen_cols:
                        continue
                    seen_cols.add(name)
                    cols.append(name)
                    if len(cols) >= 2000:
                        break
                if len(cols) >= 2000:
                    break

            mask_map = build_fls_column_mask_map(fls_policy, source="table_store", columns=cols, ctx=fls_ctx)
            if not mask_map:
                continue
            present = [c for c in mask_map.keys() if any(isinstance(r, dict) and c in r for r in sample_rows)]
            if not present:
                continue

            item.sample_rows = redact_row_dicts(sample_rows, mask_map=mask_map)
            fls_redacted_tables += 1
            if len(fls_redacted_table_ids) < 20:
                fls_redacted_table_ids.append(str(getattr(item, "table_id", "") or "")[:255])
            for c in present:
                if len(fls_redacted_columns) >= 50:
                    break
                fls_redacted_columns.add(str(c)[:500])

        if fls_redacted_tables > 0:
            _audit_fls_redaction(
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=dataset_id,
                source="table_store",
                resource_type="dataset",
                resource_id=str(dataset_id),
                details={
                    "table_count": int(fls_redacted_tables),
                    "table_ids": fls_redacted_table_ids,
                    "columns": list(fls_redacted_columns),
                    "column_count": int(len(fls_redacted_columns)),
                },
            )

    return DatasetTablesListResponse(total=len(items), items=items)


@router.get(
    "/{dataset_id}/tables/{table_id}",
    response_model=TableAssetOut,
    summary="Get table metadata by table_id",
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
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
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = _member_role(member)
    redact_rows = bool(include_sample_rows) and _should_redact_table_rows_role(role)

    fls_policy = parse_fls_policy_from_metadata(getattr(dataset, "dataset_metadata", None) or {})
    fls_ctx = FlsUserContext(account_id=account_id, role=role)

    parsed = parse_table_id(table_id)
    if parsed is None:
        raise HTTPException(status_code=400, detail=_DETAIL_INVALID_TABLE_ID)

    # Enforce document-level ACL and dataset binding.
    filter_allowed_document_ids(db, tenant_id, account_id, [parsed.document_id])

    doc = (
        db.query(DBDocument)
        .filter(DBDocument.id == parsed.document_id, DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail=_DETAIL_TABLE_NOT_FOUND)

    assets = _extract_table_assets(
        doc=doc,
        include_columns=include_columns,
        include_sample_rows=include_sample_rows,
        redact_sample_rows=redact_rows,
    )
    for a in assets:
        if a.table_id == table_id:
            # FLS: mask values in sample rows for denied columns.
            if bool(include_sample_rows) and fls_policy is not None and getattr(a, "sample_rows", None):
                sample_rows = list(a.sample_rows or [])
                seen_cols: set[str] = set()
                cols: list[str] = []
                for r in sample_rows:
                    if not isinstance(r, dict):
                        continue
                    for k in r.keys():
                        name = str(k or "")
                        if not name or name in seen_cols:
                            continue
                        seen_cols.add(name)
                        cols.append(name)
                        if len(cols) >= 2000:
                            break
                    if len(cols) >= 2000:
                        break

                mask_map = build_fls_column_mask_map(fls_policy, source="table_store", columns=cols, ctx=fls_ctx)
                if mask_map:
                    present = [c for c in mask_map.keys() if any(isinstance(r, dict) and c in r for r in sample_rows)]
                    if present:
                        a.sample_rows = redact_row_dicts(sample_rows, mask_map=mask_map)
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
                                "columns": [str(c)[:500] for c in present][:50],
                                "column_count": int(len(present)),
                            },
                        )
            return a
    raise HTTPException(status_code=404, detail=_DETAIL_TABLE_NOT_FOUND)


@router.get(
    "/{dataset_id}/tables/{table_id}/preview",
    response_model=TableQueryResponse,
    summary="Preview a table (SELECT * ... LIMIT N)",
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def preview_dataset_table(
    dataset_id: UUID,
    table_id: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = _member_role(member)
    redact_rows = _should_redact_table_rows_role(role)

    fls_policy = parse_fls_policy_from_metadata(getattr(dataset, "dataset_metadata", None) or {})
    fls_ctx = FlsUserContext(account_id=account_id, role=role)

    parsed = parse_table_id(table_id)
    if parsed is None:
        raise HTTPException(status_code=400, detail=_DETAIL_INVALID_TABLE_ID)

    filter_allowed_document_ids(db, tenant_id, account_id, [parsed.document_id])

    sql_table = sql_table_name_for_sheet(parsed.sheet_index)
    sql_table_q = quote_sqlite_ident(sql_table)
    payload = run_table_query(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        table_id=table_id,
        sql=f"SELECT * FROM {sql_table_q}",  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
        max_rows=min(int(limit), int(getattr(settings, "TABLE_QUERY_MAX_ROWS", 200) or 200)),
        max_cols=int(getattr(settings, "TABLE_QUERY_MAX_COLS", 200) or 200),
        max_bytes=int(getattr(settings, "TABLE_QUERY_MAX_BYTES", 1_000_000) or 1_000_000),
    )
    if redact_rows:
        payload = dict(payload)
        payload["rows"] = _redact_table_rows(list(payload.get("rows") or []))
    if fls_policy is not None:
        cols = [str(c) for c in (payload.get("columns") or [])]
        rows = list(payload.get("rows") or [])
        mask_map = build_fls_column_mask_map(fls_policy, source="table_store", columns=cols, ctx=fls_ctx)
        masked_cols = [c for c in cols if c in mask_map]
        if mask_map and masked_cols and rows:
            payload = dict(payload)
            payload["rows"] = redact_row_lists(rows, columns=cols, mask_map=mask_map)
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
                    "column_count": int(len(masked_cols)),
                },
            )
    return TableQueryResponse(**payload)


@router.post(
    "/{dataset_id}/tables/{table_id}/query",
    response_model=TableQueryResponse,
    summary="Run a SELECT-only SQL query against a table",
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def query_dataset_table(
    dataset_id: UUID,
    table_id: str,
    body: TableQueryRequest,
    include_sql: Annotated[bool, Query(description='Include redacted SQL for owner/admin/auditor')] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = _member_role(member)
    redact_rows = _should_redact_table_rows_role(role)

    fls_policy = parse_fls_policy_from_metadata(getattr(dataset, "dataset_metadata", None) or {})
    fls_ctx = FlsUserContext(account_id=account_id, role=role)

    parsed = parse_table_id(table_id)
    if parsed is None:
        raise HTTPException(status_code=400, detail=_DETAIL_INVALID_TABLE_ID)

    filter_allowed_document_ids(db, tenant_id, account_id, [parsed.document_id])

    max_rows = int(body.max_rows or getattr(settings, "TABLE_QUERY_MAX_ROWS", 200) or 200)
    max_cols = int(body.max_cols or getattr(settings, "TABLE_QUERY_MAX_COLS", 200) or 200)

    payload = run_table_query(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        table_id=table_id,
        sql=str(body.sql or ""),
        max_rows=min(max_rows, int(getattr(settings, "TABLE_QUERY_MAX_ROWS", 200) or 200)),
        max_cols=min(max_cols, int(getattr(settings, "TABLE_QUERY_MAX_COLS", 200) or 200)),
        max_bytes=int(getattr(settings, "TABLE_QUERY_MAX_BYTES", 1_000_000) or 1_000_000),
    )
    raw_sql = str(payload.get("sql") or body.sql or "")
    _audit_table_query(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        table_id=table_id,
        sql=raw_sql,
    )
    show_sql = bool(include_sql) and _can_view_redacted_sql_role(role)
    out_payload = dict(payload)
    if redact_rows:
        out_payload["rows"] = _redact_table_rows(list(out_payload.get("rows") or []))
    if fls_policy is not None:
        cols = [str(c) for c in (out_payload.get("columns") or [])]
        rows = list(out_payload.get("rows") or [])
        mask_map = build_fls_column_mask_map(fls_policy, source="table_store", columns=cols, ctx=fls_ctx)
        masked_cols = [c for c in cols if c in mask_map]
        if mask_map and masked_cols and rows:
            out_payload["rows"] = redact_row_lists(rows, columns=cols, mask_map=mask_map)
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
                    "column_count": int(len(masked_cols)),
                },
            )
    out_payload["sql"] = redact_sql_literals(raw_sql) if show_sql else "<hidden>"
    return TableQueryResponse(**out_payload)


@router.post(
    "/{dataset_id}/tables/{table_id}/ask",
    response_model=TableAskResponse,
    summary="TAG: Ask a question over a table (NL -> SQL -> execute -> answer)",
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def ask_dataset_table(
    dataset_id: UUID,
    table_id: str,
    body: TableAskRequest,
    include_sql: Annotated[bool, Query(description='Include redacted SQL for owner/admin/auditor')] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    if not tag_enabled():
        raise HTTPException(status_code=400, detail="TABLE_NL2SQL_ENABLED=false")
    has_llm_key = bool(str(getattr(settings, "LLM_API_KEY", "") or "").strip())
    deterministic_ok = bool(getattr(settings, "TABLE_NL2SQL_DETERMINISTIC_ONLY", False)) or bool(
        getattr(settings, "TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED", True)
    )
    if not has_llm_key and not deterministic_ok:
        raise HTTPException(status_code=400, detail="LLM_API_KEY is not configured")

    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = _member_role(member)
    redact_rows = _should_redact_table_rows_role(role)

    fls_policy = parse_fls_policy_from_metadata(getattr(dataset, "dataset_metadata", None) or {})
    fls_ctx = FlsUserContext(account_id=account_id, role=role)

    parsed = parse_table_id(table_id)
    if parsed is None:
        raise HTTPException(status_code=400, detail=_DETAIL_INVALID_TABLE_ID)

    filter_allowed_document_ids(db, tenant_id, account_id, [parsed.document_id])

    doc = (
        db.query(DBDocument)
        .filter(DBDocument.id == parsed.document_id, DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail=_DETAIL_TABLE_NOT_FOUND)

    # Extract schema for the specific table_id.
    meta = getattr(doc, "doc_metadata", None) or {}
    store = meta.get("table_store") if isinstance(meta, dict) else None
    tables = store.get("tables") if isinstance(store, dict) else None
    columns: list[dict[str, Any]] = []
    sample_rows: list[dict[str, Any]] = []
    sheet_name: str | None = None
    if isinstance(tables, list):
        for t in tables:
            if not isinstance(t, dict):
                continue
            if str(t.get("table_id") or "").strip() != table_id:
                continue
            cols = t.get("columns")
            if isinstance(cols, list):
                columns = [c for c in cols if isinstance(c, dict)]
            rows = t.get("sample_rows")
            if isinstance(rows, list):
                sample_rows = [r for r in rows if isinstance(r, dict)]
            sn = t.get("sheet_name")
            sheet_name = str(sn).strip() if sn is not None else None
            break

    sql_table = sql_table_name_for_sheet(parsed.sheet_index)
    max_rows = int(body.max_rows or getattr(settings, "TABLE_QUERY_MAX_ROWS", 200) or 200)
    max_rows = min(max_rows, int(getattr(settings, "TABLE_QUERY_MAX_ROWS", 200) or 200))

    sql_generation_mode = "llm"
    schema_link_diagnostics: dict[str, Any] | None = None
    planner_diagnostics: dict[str, Any] | None = None
    join_provenance: list[dict[str, Any]] | None = None
    sql_fingerprint: str | None = None
    try:
        sql, sql_generation_mode, sql_meta = generate_sql_for_table_with_metadata(
            question=str(body.question or ""),
            sql_table=sql_table,
            columns=columns,
            max_rows=max_rows,
            sample_rows=sample_rows,
            table_aliases=[str(table_id), str(getattr(doc, "filename", "") or ""), str(sheet_name or "")],
        )
        schema_link = sql_meta.get("schema_link") if isinstance(sql_meta, dict) else None
        schema_link_diagnostics = schema_link if isinstance(schema_link, dict) else None
        planner = sql_meta.get("planner") if isinstance(sql_meta, dict) else None
        planner_diagnostics = planner if isinstance(planner, dict) else None
        joins = sql_meta.get("join_provenance") if isinstance(sql_meta, dict) else None
        if isinstance(joins, list):
            join_provenance = [j for j in joins if isinstance(j, dict)][:10]
        sql_fingerprint = str(
            (sql_meta.get("sql_fingerprint") if isinstance(sql_meta, dict) else None)
            or (planner_diagnostics.get("sql_fingerprint") if isinstance(planner_diagnostics, dict) else None)
            or ""
        ).strip() or None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"nl2sql_failed: {str(exc)[:200]}") from exc
    if not sql.strip():
        raise HTTPException(status_code=400, detail="nl2sql_failed: empty sql")
    if not sql_fingerprint:
        sql_fingerprint = fingerprint_sql(sql, length=16) or None

    result = run_table_query(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        table_id=table_id,
        sql=sql,
        max_rows=max_rows,
        max_cols=int(getattr(settings, "TABLE_QUERY_MAX_COLS", 200) or 200),
        max_bytes=int(getattr(settings, "TABLE_QUERY_MAX_BYTES", 1_000_000) or 1_000_000),
        planner_diagnostics=planner_diagnostics,
        expected_sql_fingerprint=sql_fingerprint,
    )
    planner_execution_mismatch = (
        result.get("planner_execution_mismatch")
        if isinstance(result.get("planner_execution_mismatch"), dict)
        else None
    )
    if (
        bool(getattr(settings, "TABLE_TAG_PLANNER_MISMATCH_STRICT", False))
        and planner_execution_mismatch
        and bool(planner_execution_mismatch.get("mismatch"))
    ):
        raise HTTPException(status_code=409, detail="planner_execution_mismatch")
    if not bool(getattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", False)):
        raise HTTPException(
            status_code=400,
            detail="TABLE_LLM_ALLOW_RESULT_EGRESS=false (answer drafting requires sending query results to an LLM)",
        )

    # FLS: redact denied columns before any LLM call.
    data_payload = dict(result)
    if fls_policy is not None:
        cols = [str(c) for c in (data_payload.get("columns") or [])]
        rows = list(data_payload.get("rows") or [])
        mask_map = build_fls_column_mask_map(fls_policy, source="table_store", columns=cols, ctx=fls_ctx)
        masked_cols = [c for c in cols if c in mask_map]
        if mask_map and masked_cols and rows:
            data_payload["rows"] = redact_row_lists(rows, columns=cols, mask_map=mask_map)
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
                    "column_count": int(len(masked_cols)),
                },
            )
    try:
        answer = generate_answer_from_result(
            question=str(body.question or ""),
            sql=str(data_payload.get("sql") or sql),
            result=data_payload,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"answer_failed: {str(exc)[:200]}") from exc

    raw_sql = str(result.get("sql") or sql or "")
    _audit_table_query(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        table_id=table_id,
        sql=raw_sql,
    )
    show_sql = bool(include_sql) and _can_view_redacted_sql_role(role)
    redacted_sql = redact_sql_literals(raw_sql) if show_sql else None
    if redact_rows:
        data_payload["rows"] = _redact_table_rows(list(data_payload.get("rows") or []))
    data_payload["sql"] = redacted_sql or "<hidden>"
    return TableAskResponse(
        answer=answer,
        sql=redacted_sql,
        data=TableQueryResponse(**data_payload),
        sql_generation_mode=str(sql_generation_mode or "llm"),
        schema_link_diagnostics=schema_link_diagnostics,
        planner_diagnostics=planner_diagnostics,
        join_provenance=join_provenance,
        sql_fingerprint=sql_fingerprint,
        planner_execution_mismatch=planner_execution_mismatch,
    )


@router.post(
    "/{dataset_id}/tables/{table_id}/lotus/sem-filter",
    response_model=TableQueryResponse,
    summary="LOTUS (optional): semantic filter over a table (falls back to NL->SQL when LOTUS unavailable)",
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def lotus_sem_filter_dataset_table(
    dataset_id: UUID,
    table_id: str,
    body: LotusSemFilterRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    if not bool(getattr(settings, "TABLE_LOTUS_ENABLED", False)):
        raise HTTPException(status_code=400, detail="TABLE_LOTUS_ENABLED=false")
    if not str(getattr(settings, "LLM_API_KEY", "") or "").strip():
        raise HTTPException(status_code=400, detail="LLM_API_KEY is not configured")

    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = _member_role(member)
    redact_rows = _should_redact_table_rows_role(role)

    fls_policy = parse_fls_policy_from_metadata(getattr(dataset, "dataset_metadata", None) or {})
    fls_ctx = FlsUserContext(account_id=account_id, role=role)

    parsed = parse_table_id(table_id)
    if parsed is None:
        raise HTTPException(status_code=400, detail=_DETAIL_INVALID_TABLE_ID)

    filter_allowed_document_ids(db, tenant_id, account_id, [parsed.document_id])

    doc = (
        db.query(DBDocument)
        .filter(DBDocument.id == parsed.document_id, DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail=_DETAIL_TABLE_NOT_FOUND)

    sql_table = sql_table_name_for_sheet(parsed.sheet_index)
    sql_table_q = quote_sqlite_ident(sql_table)
    output_rows = int(body.max_rows or getattr(settings, "TABLE_QUERY_MAX_ROWS", 200) or 200)
    output_rows = min(output_rows, int(getattr(settings, "TABLE_QUERY_MAX_ROWS", 200) or 200))

    avail = lotus_available()
    if avail.ok:
        # Load a bounded sample into pandas.
        import sqlite3

        import pandas as pd  # type: ignore

        max_in_rows = min(
            int(getattr(settings, "TABLE_LOTUS_MAX_ROWS", 20_000) or 20_000),
            int(getattr(settings, "TABLE_SEM_FILTER_MAX_IN_ROWS", 2000) or 2000),
            100_000,
        )
        max_in_cols = int(getattr(settings, "TABLE_SEM_FILTER_MAX_COLS", 30) or 30)
        db_path = table_store_path(tenant_id=tenant_id, dataset_id=dataset_id, document_id=parsed.document_id)
        if not db_path.exists():
            raise HTTPException(status_code=404, detail="table store not found")
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
            try:
                # Avoid loading extremely wide tables into pandas when we only need a small column set
                # for semantic filtering.
                cols: list[str] = []
                try:
                    cur = conn.execute(f"PRAGMA table_info({sql_table_q})")
                    cols = [str(r[1]) for r in cur.fetchall() if r and len(r) > 1 and str(r[1] or "").strip()]
                except Exception:
                    cols = []

                if max_in_cols > 0 and cols:
                    cols = cols[: int(max_in_cols)]
                if cols:
                    def _q(ident: str) -> str:
                        return '"' + str(ident).replace('"', '""') + '"'

                    select_list = ", ".join([_q(c) for c in cols])
                    query = f"SELECT {select_list} FROM {sql_table_q} LIMIT {int(max_in_rows)}"  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
                else:
                    query = f"SELECT * FROM {sql_table_q} LIMIT {int(max_in_rows)}"  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
                df = pd.read_sql_query(query, conn)
                if fls_policy is not None:
                    # Defense-in-depth: avoid sending denied columns to LOTUS/LLM flows.
                    try:
                        df_cols = [str(c) for c in (getattr(df, "columns", []) or [])]
                        mask_map = build_fls_column_mask_map(fls_policy, source="table_store", columns=df_cols, ctx=fls_ctx)
                        for c, mask in mask_map.items():
                            if c in df.columns:  # type: ignore[operator]
                                df[c] = str(mask)  # type: ignore[index]
                    except Exception as exc:
                        logger.debug("Ignoring LOTUS table FLS mask preparation failure: %s", exc)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"table_load_failed: {str(exc)[:200]}") from exc

        try:
            filtered = lotus_sem_filter(df, user_instruction=str(body.user_instruction or ""), strategy=str(body.strategy or "cot"))
        except Exception as exc:  # noqa: BLE001
            # Fall back to NL->SQL below.
            avail = type(avail)(ok=False, reason=f"lotus failed: {str(exc)[:200]}")  # type: ignore[misc]
        else:
            cols = [str(c) for c in (getattr(filtered, "columns", []) or [])]
            rows: list[list[Any]] = []
            truncated = False
            for i, row in enumerate(filtered.itertuples(index=False, name=None)):  # type: ignore[attr-defined]
                if i >= output_rows:
                    truncated = True
                    break
                rows.append([x if x is None or isinstance(x, (str, int, float, bool)) else str(x) for x in (row or ())])
            if redact_rows:
                rows = _redact_table_rows(rows)
            if fls_policy is not None:
                mask_map = build_fls_column_mask_map(fls_policy, source="table_store", columns=cols, ctx=fls_ctx)
                masked_cols = [c for c in cols if c in mask_map]
                if mask_map and masked_cols and rows:
                    rows = redact_row_lists(rows, columns=cols, mask_map=mask_map)
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
                            "column_count": int(len(masked_cols)),
                        },
                    )
            return TableQueryResponse(sql=f"LOTUS sem_filter({sql_table})", columns=cols, rows=rows, truncated=truncated)

    # Fallback: use NL->SQL to generate a WHERE clause and execute safely.
    if not tag_enabled():
        raise HTTPException(status_code=400, detail=f"LOTUS unavailable: {avail.reason or 'unknown'} (and TABLE_NL2SQL_ENABLED=false)")

    # Reuse the NL->SQL generator with an explicit "return rows" framing.
    prompt_q = f"Filter rows that match: {str(body.user_instruction or '').strip()}. Return the matching rows."
    try:
        sql = generate_sql_for_table(
            question=prompt_q,
            sql_table=sql_table,
            columns=[],
            max_rows=output_rows,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"nl2sql_failed: {str(exc)[:200]}") from exc

    payload = run_table_query(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        table_id=table_id,
        sql=sql,
        max_rows=output_rows,
        max_cols=int(getattr(settings, "TABLE_QUERY_MAX_COLS", 200) or 200),
        max_bytes=int(getattr(settings, "TABLE_QUERY_MAX_BYTES", 1_000_000) or 1_000_000),
    )
    if redact_rows:
        payload = dict(payload)
        payload["rows"] = _redact_table_rows(list(payload.get("rows") or []))
    if fls_policy is not None:
        cols = [str(c) for c in (payload.get("columns") or [])]
        rows = list(payload.get("rows") or [])
        mask_map = build_fls_column_mask_map(fls_policy, source="table_store", columns=cols, ctx=fls_ctx)
        masked_cols = [c for c in cols if c in mask_map]
        if mask_map and masked_cols and rows:
            payload = dict(payload)
            payload["rows"] = redact_row_lists(rows, columns=cols, mask_map=mask_map)
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
                    "column_count": int(len(masked_cols)),
                },
            )
    return TableQueryResponse(**payload)
