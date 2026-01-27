"""
Dataset Tables (TAG) API.

This provides a safe, SQL-first interface for structured documents (CSV/XLS/XLSX)
that were ingested into the per-document table store.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.models.document import Document as DBDocument
from app.services.dataset_service import DatasetService
from app.services.document_access import filter_allowed_document_ids, get_allowed_document_id_sets
from app.services.table_store_service import run_table_query
from app.services.table_store import parse_table_id, table_store_path
from app.services.table_tag_service import generate_answer_from_result, generate_sql_for_table, tag_enabled
from app.services.lotus_bridge import lotus_available, sem_filter as lotus_sem_filter
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


router = APIRouter()


def _extract_table_assets(
    *,
    doc: DBDocument,
    include_columns: bool,
    include_sample_rows: bool,
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
    skip: int = Query(default=0, ge=0, description="Document-level offset (not table-level)"),
    limit: int = Query(default=100, ge=1, le=500, description="Document-level limit (not table-level)"),
    include_columns: bool = Query(default=False, description="Include column schema in each item"),
    include_sample_rows: bool = Query(default=False, description="Include sample rows in each item"),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

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
    q = q.filter(DBDocument.file_type.in_(["csv", "xlsx", "xls"]))

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
        items.extend(_extract_table_assets(doc=d, include_columns=include_columns, include_sample_rows=include_sample_rows))

    return DatasetTablesListResponse(total=len(items), items=items)


@router.get(
    "/{dataset_id}/tables/{table_id}",
    response_model=TableAssetOut,
    summary="Get table metadata by table_id",
)
def get_dataset_table(
    dataset_id: UUID,
    table_id: str,
    include_columns: bool = Query(default=True),
    include_sample_rows: bool = Query(default=True),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    parsed = parse_table_id(table_id)
    if parsed is None:
        raise HTTPException(status_code=400, detail="invalid table_id")

    # Enforce document-level ACL and dataset binding.
    filter_allowed_document_ids(db, tenant_id, account_id, [parsed.document_id])

    doc = (
        db.query(DBDocument)
        .filter(DBDocument.id == parsed.document_id, DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="table not found")

    assets = _extract_table_assets(doc=doc, include_columns=include_columns, include_sample_rows=include_sample_rows)
    for a in assets:
        if a.table_id == table_id:
            return a
    raise HTTPException(status_code=404, detail="table not found")


@router.get(
    "/{dataset_id}/tables/{table_id}/preview",
    response_model=TableQueryResponse,
    summary="Preview a table (SELECT * ... LIMIT N)",
)
def preview_dataset_table(
    dataset_id: UUID,
    table_id: str,
    limit: int = Query(default=20, ge=1, le=500),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    parsed = parse_table_id(table_id)
    if parsed is None:
        raise HTTPException(status_code=400, detail="invalid table_id")

    filter_allowed_document_ids(db, tenant_id, account_id, [parsed.document_id])

    sql_table = f"sheet_{int(parsed.sheet_index)}"
    payload = run_table_query(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        table_id=table_id,
        sql=f'SELECT * FROM "{sql_table}"',
        max_rows=min(int(limit), int(getattr(settings, "TABLE_QUERY_MAX_ROWS", 200) or 200)),
        max_cols=int(getattr(settings, "TABLE_QUERY_MAX_COLS", 200) or 200),
        max_bytes=int(getattr(settings, "TABLE_QUERY_MAX_BYTES", 1_000_000) or 1_000_000),
    )
    return TableQueryResponse(**payload)


@router.post(
    "/{dataset_id}/tables/{table_id}/query",
    response_model=TableQueryResponse,
    summary="Run a SELECT-only SQL query against a table",
)
def query_dataset_table(
    dataset_id: UUID,
    table_id: str,
    body: TableQueryRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    parsed = parse_table_id(table_id)
    if parsed is None:
        raise HTTPException(status_code=400, detail="invalid table_id")

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
    return TableQueryResponse(**payload)


@router.post(
    "/{dataset_id}/tables/{table_id}/ask",
    response_model=TableAskResponse,
    summary="TAG: Ask a question over a table (NL -> SQL -> execute -> answer)",
)
def ask_dataset_table(
    dataset_id: UUID,
    table_id: str,
    body: TableAskRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    if not tag_enabled():
        raise HTTPException(status_code=400, detail="TABLE_NL2SQL_ENABLED=false")
    if not str(getattr(settings, "LLM_API_KEY", "") or "").strip():
        raise HTTPException(status_code=400, detail="LLM_API_KEY is not configured")

    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    parsed = parse_table_id(table_id)
    if parsed is None:
        raise HTTPException(status_code=400, detail="invalid table_id")

    filter_allowed_document_ids(db, tenant_id, account_id, [parsed.document_id])

    doc = (
        db.query(DBDocument)
        .filter(DBDocument.id == parsed.document_id, DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="table not found")

    # Extract schema for the specific table_id.
    meta = getattr(doc, "doc_metadata", None) or {}
    store = meta.get("table_store") if isinstance(meta, dict) else None
    tables = store.get("tables") if isinstance(store, dict) else None
    columns: list[dict[str, Any]] = []
    if isinstance(tables, list):
        for t in tables:
            if not isinstance(t, dict):
                continue
            if str(t.get("table_id") or "").strip() != table_id:
                continue
            cols = t.get("columns")
            if isinstance(cols, list):
                columns = [c for c in cols if isinstance(c, dict)]
            break

    sql_table = f"sheet_{int(parsed.sheet_index)}"
    max_rows = int(body.max_rows or getattr(settings, "TABLE_QUERY_MAX_ROWS", 200) or 200)
    max_rows = min(max_rows, int(getattr(settings, "TABLE_QUERY_MAX_ROWS", 200) or 200))

    try:
        sql = generate_sql_for_table(question=str(body.question or ""), sql_table=sql_table, columns=columns, max_rows=max_rows)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"nl2sql_failed: {str(exc)[:200]}") from exc
    if not sql.strip():
        raise HTTPException(status_code=400, detail="nl2sql_failed: empty sql")

    result = run_table_query(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        table_id=table_id,
        sql=sql,
        max_rows=max_rows,
        max_cols=int(getattr(settings, "TABLE_QUERY_MAX_COLS", 200) or 200),
        max_bytes=int(getattr(settings, "TABLE_QUERY_MAX_BYTES", 1_000_000) or 1_000_000),
    )
    try:
        answer = generate_answer_from_result(question=str(body.question or ""), sql=str(result.get("sql") or sql), result=result)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"answer_failed: {str(exc)[:200]}") from exc

    return TableAskResponse(
        answer=answer,
        sql=str(result.get("sql") or sql),
        data=TableQueryResponse(**result),
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
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    if not bool(getattr(settings, "TABLE_LOTUS_ENABLED", False)):
        raise HTTPException(status_code=400, detail="TABLE_LOTUS_ENABLED=false")
    if not str(getattr(settings, "LLM_API_KEY", "") or "").strip():
        raise HTTPException(status_code=400, detail="LLM_API_KEY is not configured")

    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    parsed = parse_table_id(table_id)
    if parsed is None:
        raise HTTPException(status_code=400, detail="invalid table_id")

    filter_allowed_document_ids(db, tenant_id, account_id, [parsed.document_id])

    doc = (
        db.query(DBDocument)
        .filter(DBDocument.id == parsed.document_id, DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="table not found")

    sql_table = f"sheet_{int(parsed.sheet_index)}"
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
        db_path = table_store_path(tenant_id=tenant_id, dataset_id=dataset_id, document_id=parsed.document_id)
        if not db_path.exists():
            raise HTTPException(status_code=404, detail="table store not found")
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
            try:
                df = pd.read_sql_query(f'SELECT * FROM "{sql_table}" LIMIT {int(max_in_rows)}', conn)
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
            cols = [str(c) for c in list(getattr(filtered, "columns", []) or [])]
            rows: list[list[Any]] = []
            truncated = False
            for i, row in enumerate(filtered.itertuples(index=False, name=None)):  # type: ignore[attr-defined]
                if i >= output_rows:
                    truncated = True
                    break
                rows.append([x if x is None or isinstance(x, (str, int, float, bool)) else str(x) for x in (row or ())])
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
    return TableQueryResponse(**payload)
