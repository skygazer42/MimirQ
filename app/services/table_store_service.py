"""
Structured table store import/query (TAG).

This module intentionally keeps execution *declarative* and safe:
- Storage is per-document SQLite file under TABLE_STORE_DIR (tenant/dataset scoped).
- Import uses pandas to read CSV/XLS/XLSX and write to sqlite (no arbitrary code execution).
- Query execution is SELECT-only and uses sqlite authorizer to restrict table access.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from uuid import UUID
import datetime as dt
import json
import re
import sqlite3
import time

import pandas as pd  # type: ignore

from app.core.config import settings
from app.services.table_store import (
    format_table_id,
    parse_table_id,
    sql_table_name_for_sheet,
    table_store_path,
)


_SQL_SELECT_PREFIX_RE = re.compile(r"^\s*(with\b|select\b)", re.IGNORECASE)


@dataclass(frozen=True)
class TableAsset:
    table_id: str
    document_id: UUID
    sheet_index: int
    sheet_name: Optional[str]
    sql_table: str
    row_count: int
    col_count: int
    truncated: bool
    columns: list[dict[str, Any]]
    sample_rows: list[dict[str, Any]]


def _jsonify_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (dt.datetime, dt.date)):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    # Pandas / numpy scalars
    try:
        if hasattr(v, "item"):
            return v.item()
    except Exception:
        pass
    return str(v)


def _df_sample_rows(df: "pd.DataFrame", *, sample_rows: int) -> list[dict[str, Any]]:
    n = max(0, int(sample_rows or 0))
    if n <= 0:
        return []
    head = df.head(n)
    records: list[dict[str, Any]] = []
    try:
        raw = head.to_dict(orient="records")
    except Exception:
        raw = []
    for row in raw or []:
        if not isinstance(row, dict):
            continue
        rec: dict[str, Any] = {}
        for k, v in row.items():
            rec[str(k)] = _jsonify_value(v)
        records.append(rec)
        if len(records) >= n:
            break
    return records


def _df_columns(df: "pd.DataFrame") -> list[dict[str, Any]]:
    cols: list[dict[str, Any]] = []
    try:
        dtypes = getattr(df, "dtypes", None)
    except Exception:
        dtypes = None
    for c in list(df.columns):
        name = str(c)
        dtype = None
        try:
            if dtypes is not None:
                dtype = str(dtypes[c])
        except Exception:
            dtype = None
        cols.append({"name": name, "dtype": dtype})
        if len(cols) >= 2000:
            break
    return cols


def _connect_rw(path: Path) -> sqlite3.Connection:
    # Ensure parent directory exists; storage path itself is deterministic (not user-controlled).
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    conn = sqlite3.connect(str(path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _connect_ro(path: Path) -> sqlite3.Connection:
    # Read-only query connection (prevents writes even if authorizer is bypassed).
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def import_table_document(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
    file_path: Path,
    max_rows: int,
    max_cols: int,
    sample_rows: int,
) -> list[TableAsset]:
    """
    Import a table-like document into its per-document SQLite store.

    Returns a list of table assets (CSV: 1; Excel: >=1).
    """
    ext = file_path.suffix.lower()
    if ext not in {".csv", ".xls", ".xlsx"}:
        raise ValueError("unsupported table file type")

    out_path = table_store_path(tenant_id=tenant_id, dataset_id=dataset_id, document_id=document_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Best-effort: reset store to avoid stale tables on re-ingest.
    try:
        if out_path.exists():
            out_path.unlink()
    except Exception:
        # If unlink fails (e.g. concurrent reader), we will overwrite per table below.
        pass

    if ext == ".csv":
        df, truncated = _read_csv(file_path, max_rows=max_rows, max_cols=max_cols)
        return _write_single_sheet(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            df=df,
            sheet_index=0,
            sheet_name=None,
            truncated=truncated,
            sample_rows=sample_rows,
        )

    # Excel (.xls/.xlsx)
    return _import_excel(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        file_path=file_path,
        max_rows=max_rows,
        max_cols=max_cols,
        sample_rows=sample_rows,
    )


def _read_csv(path: Path, *, max_rows: int, max_cols: int) -> tuple["pd.DataFrame", bool]:
    nrows = max(0, int(max_rows or 0)) or None
    # pandas will infer delimiter by default; keep it simple for now.
    df = pd.read_csv(str(path), nrows=nrows, dtype_backend="numpy_nullable", encoding_errors="replace")  # type: ignore[call-arg]
    truncated = bool(nrows is not None and int(getattr(df, "shape", (0, 0))[0]) >= int(nrows))
    if max_cols and int(max_cols) > 0 and int(getattr(df, "shape", (0, 0))[1]) > int(max_cols):
        df = df.iloc[:, : int(max_cols)]
    return df, truncated


def _import_excel(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
    file_path: Path,
    max_rows: int,
    max_cols: int,
    sample_rows: int,
) -> list[TableAsset]:
    # Keep this simple and robust: use pandas for both .xls and .xlsx.
    try:
        xls = pd.ExcelFile(str(file_path))
    except Exception as exc:
        raise RuntimeError(f"excel_open_failed: {str(exc)[:200]}") from exc

    assets: list[TableAsset] = []
    sheet_names: list[str] = []
    try:
        sheet_names = list(getattr(xls, "sheet_names", []) or [])
    except Exception:
        sheet_names = []

    if not sheet_names:
        # Produce an empty sheet0 table for consistency.
        empty = pd.DataFrame()
        return _write_single_sheet(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            df=empty,
            sheet_index=0,
            sheet_name=None,
            truncated=False,
            sample_rows=sample_rows,
        )

    for idx, name in enumerate(sheet_names):
        nrows = max(0, int(max_rows or 0)) or None
        try:
            df = pd.read_excel(xls, sheet_name=name, nrows=nrows, dtype_backend="numpy_nullable")  # type: ignore[call-arg]
        except Exception:
            # Best-effort: skip unreadable sheets.
            continue
        truncated = bool(nrows is not None and int(getattr(df, "shape", (0, 0))[0]) >= int(nrows))
        if max_cols and int(max_cols) > 0 and int(getattr(df, "shape", (0, 0))[1]) > int(max_cols):
            df = df.iloc[:, : int(max_cols)]
        assets.extend(
            _write_single_sheet(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=document_id,
                df=df,
                sheet_index=int(idx),
                sheet_name=str(name),
                truncated=truncated,
                sample_rows=sample_rows,
            )
        )

    return assets or []


def _write_single_sheet(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
    df: "pd.DataFrame",
    sheet_index: int,
    sheet_name: Optional[str],
    truncated: bool,
    sample_rows: int,
) -> list[TableAsset]:
    out_path = table_store_path(tenant_id=tenant_id, dataset_id=dataset_id, document_id=document_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sql_table = sql_table_name_for_sheet(sheet_index)
    table_id = format_table_id(document_id=document_id, sheet_index=sheet_index)

    conn = _connect_rw(out_path)
    try:
        # Replace the sheet table.
        conn.execute(f'DROP TABLE IF EXISTS "{sql_table}";')
        # Use pandas to write; it will create columns with proper quoting.
        df.to_sql(sql_table, conn, if_exists="replace", index=False)
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    rows = int(getattr(df, "shape", (0, 0))[0])
    cols = int(getattr(df, "shape", (0, 0))[1])

    asset = TableAsset(
        table_id=table_id,
        document_id=document_id,
        sheet_index=int(sheet_index),
        sheet_name=(sheet_name if sheet_name else None),
        sql_table=sql_table,
        row_count=rows,
        col_count=cols,
        truncated=bool(truncated),
        columns=_df_columns(df),
        sample_rows=_df_sample_rows(df, sample_rows=sample_rows),
    )
    return [asset]


def list_tables_from_metadata(meta: dict[str, Any]) -> list[TableAsset]:
    """
    Best-effort helper: convert document metadata into `TableAsset` models.

    Used by the dataset tables API to avoid reading SQLite files for listing.
    """
    if not isinstance(meta, dict):
        return []
    store = meta.get("table_store")
    if not isinstance(store, dict):
        return []
    raw_tables = store.get("tables")
    if not isinstance(raw_tables, list):
        return []
    out: list[TableAsset] = []
    for t in raw_tables:
        if not isinstance(t, dict):
            continue
        tid = t.get("table_id")
        parsed = parse_table_id(str(tid or ""))
        if parsed is None:
            continue
        try:
            doc_id = parsed.document_id
            sheet_index = int(parsed.sheet_index)
        except Exception:
            continue
        sql_table = sql_table_name_for_sheet(sheet_index)
        out.append(
            TableAsset(
                table_id=str(tid),
                document_id=doc_id,
                sheet_index=sheet_index,
                sheet_name=(str(t.get("sheet_name")) if t.get("sheet_name") is not None else None),
                sql_table=sql_table,
                row_count=int(t.get("row_count") or 0),
                col_count=int(t.get("col_count") or 0),
                truncated=bool(t.get("truncated") or False),
                columns=list(t.get("columns") or []),
                sample_rows=list(t.get("sample_rows") or []),
            )
        )
    return out


def run_table_query(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    table_id: str,
    sql: str,
    max_rows: int,
    max_cols: int,
    max_bytes: int,
) -> dict[str, Any]:
    """
    Execute a SELECT-only query against a single table within a document store.

    Returns: {columns: [...], rows: [...], truncated: bool, sql: "..."}
    """
    parsed = parse_table_id(table_id)
    if parsed is None:
        raise ValueError("invalid table_id")

    raw_sql = str(sql or "")
    if not raw_sql.strip():
        raise ValueError("sql is required")
    max_sql_chars = int(getattr(settings, "TABLE_QUERY_MAX_SQL_CHARS", 20_000) or 20_000)
    if max_sql_chars > 0 and len(raw_sql) > int(max_sql_chars):
        raise ValueError(f"sql_too_long (max {int(max_sql_chars)})")
    if ";" in raw_sql:
        raise ValueError("multiple statements are not allowed")
    if not _SQL_SELECT_PREFIX_RE.match(raw_sql):
        raise ValueError("only SELECT queries are allowed")

    sql_table = sql_table_name_for_sheet(parsed.sheet_index)
    db_path = table_store_path(tenant_id=tenant_id, dataset_id=dataset_id, document_id=parsed.document_id)
    if not db_path.exists():
        raise FileNotFoundError("table store not found")

    # Enforce LIMIT if absent (best-effort). This keeps the endpoint safe by default.
    limit = max(1, int(max_rows or 0))
    normalized = raw_sql.strip()
    if re.search(r"\blimit\b", normalized, flags=re.IGNORECASE) is None:
        normalized = f"{normalized}\nLIMIT {limit}"
    else:
        # Best-effort: reject obvious LIMIT literals that exceed the server max_rows.
        # This does not attempt to fully parse SQL; progress/time limits are the primary guard.
        try:
            limits = [int(m.group(1)) for m in re.finditer(r"\blimit\s+(\d+)\b", normalized, flags=re.IGNORECASE)]
        except Exception:
            limits = []
        if limits and max(limits) > limit:
            raise ValueError(f"limit_too_large (max {limit})")

    # SQLite authorizer: deny writes/pragma/attach and restrict reads to our sheet table only.
    conn = _connect_ro(db_path)
    truncated = False
    try:
        # Time budget guardrail (DoS defense-in-depth). Uses SQLite VM progress handler.
        timeout_sec = float(getattr(settings, "TABLE_QUERY_TIMEOUT_SEC", 0.0) or 0.0)
        progress_ops = int(getattr(settings, "TABLE_QUERY_PROGRESS_OPS", 0) or 0)
        if timeout_sec > 0 and progress_ops > 0:
            start = time.monotonic()

            def _progress() -> int:  # pragma: no cover (timing dependent)
                return 1 if (time.monotonic() - start) > timeout_sec else 0

            try:
                conn.set_progress_handler(_progress, int(progress_ops))
            except Exception:
                pass

        _apply_sqlite_readonly_authorizer(conn, allowed_tables={sql_table})
        try:
            cur = conn.execute(normalized)
        except sqlite3.OperationalError as exc:
            msg = str(exc or "").lower()
            if "interrupted" in msg and timeout_sec > 0:
                raise TimeoutError(f"query_timeout ({timeout_sec:.1f}s)") from exc
            raise
        col_names = [d[0] for d in (cur.description or [])]
        if max_cols and int(max_cols) > 0 and len(col_names) > int(max_cols):
            col_names = col_names[: int(max_cols)]
            truncated = True

        out_rows: list[list[Any]] = []
        bytes_used = 0
        max_bytes_i = max(10_000, int(max_bytes or 0))
        for row in cur.fetchmany(limit + 1):
            if len(out_rows) >= limit:
                truncated = True
                break
            # sqlite3.Row is tuple-like
            values = list(row)[: len(col_names)]
            out_rows.append([_jsonify_value(v) for v in values])
            try:
                bytes_used += len(json.dumps(out_rows[-1], ensure_ascii=False))
            except Exception:
                bytes_used += 0
            if bytes_used > max_bytes_i:
                truncated = True
                break

        return {"columns": col_names, "rows": out_rows, "truncated": bool(truncated), "sql": normalized}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _apply_sqlite_readonly_authorizer(conn: sqlite3.Connection, *, allowed_tables: set[str]) -> None:
    """
    Set a conservative authorizer:
    - deny writes / schema changes / pragma / attach
    - allow reads only from allowed_tables
    """
    # SQLITE_* action codes are available via sqlite3 module.
    deny = sqlite3.SQLITE_DENY
    ok = sqlite3.SQLITE_OK

    allowed = {str(t) for t in (allowed_tables or set()) if str(t)}
    # SQLite may read schema tables during query compilation/execution.
    # Allowing schema reads is safe within our per-document DB (no cross-tenant access),
    # while still preventing access to other user tables via the allowed set.
    schema_tables = {"sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_temp_schema"}

    # Precompute deny list once; the authorizer callback may be called many times per query.
    deny_actions: set[int] = {
        sqlite3.SQLITE_PRAGMA,
        sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH,
        sqlite3.SQLITE_ALTER_TABLE,
        sqlite3.SQLITE_CREATE_INDEX,
        sqlite3.SQLITE_CREATE_TABLE,
        sqlite3.SQLITE_CREATE_TEMP_INDEX,
        sqlite3.SQLITE_CREATE_TEMP_TABLE,
        sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
        sqlite3.SQLITE_CREATE_TEMP_VIEW,
        sqlite3.SQLITE_CREATE_TRIGGER,
        sqlite3.SQLITE_CREATE_VIEW,
        sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_DROP_INDEX,
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_INDEX,
        sqlite3.SQLITE_DROP_TEMP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_TRIGGER,
        sqlite3.SQLITE_DROP_TEMP_VIEW,
        sqlite3.SQLITE_DROP_TRIGGER,
        sqlite3.SQLITE_DROP_VIEW,
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_REINDEX,
        sqlite3.SQLITE_UPDATE,
    }
    # Not all sqlite3 builds expose SQLITE_VACUUM.
    vacuum_code = getattr(sqlite3, "SQLITE_VACUUM", None)
    if isinstance(vacuum_code, int):
        deny_actions.add(int(vacuum_code))

    def auth(action_code: int, arg1: Any, arg2: Any, dbname: Any, source: Any) -> int:  # noqa: ANN401
        # Block non-read operations.
        if action_code in deny_actions:
            return deny

        # Restrict table reads to the allowed set.
        if action_code == sqlite3.SQLITE_READ:
            table = str(arg1 or "")
            if table and table not in allowed and table not in schema_tables:
                return deny
            return ok

        return ok

    conn.set_authorizer(auth)
