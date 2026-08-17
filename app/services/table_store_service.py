"""
Structured table store import/query (TAG).

This module intentionally keeps execution *declarative* and safe:
- Storage is per-document SQLite file under TABLE_STORE_DIR (tenant/dataset scoped).
- Import uses pandas to read CSV/XLS/XLSX and write to sqlite (no arbitrary code execution).
- Query execution is SELECT-only and uses sqlite authorizer to restrict table access.
"""

import datetime as dt
import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any
from uuid import UUID

import pandas as pd  # type: ignore

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.services.table_sql_fingerprint import fingerprint_sql
from app.services.table_store import (
    format_table_id,
    parse_table_id,
    quote_sqlite_ident,
    sql_table_name_for_sheet,
    table_store_path,
)

logger = get_logger(__name__)
_TABLE_STORE_FALLBACK_LOG_MESSAGE = "Ignoring non-critical table-store fallback failure: %s"

_SQL_SELECT_PREFIX_RE = re.compile(r"^\s*(with\b|select\b)", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")
_BOM_RE = re.compile(r"^\ufeff+")
_NUMERIC_ONLY_RE = re.compile(r"^\s*[-+]?(?:\d+(?:\.\d+)?|\.\d+)\s*$")
_MD_TABLE_SEP_CELL_RE = re.compile(r"^\s*:?-{3,}:?\s*$")
_DOCX_TABLE_CAPTION_RE = re.compile(
    r"(?i)^\s*(?:table|tab\.?|appendix\s+table|鐞?\s*[\dIVXLC娑撯偓娴滃奔绗侀崶娑楃安閸忣厺绔烽崗顐＄瘈閸椾箽+"
    r"(?:\s*[:閿?\-])?\s*.+$"
)
_SQL_TABLE_REF_RE = re.compile(
    r'\b(?:from|join)\s+(?:"([^"]+)"|([A-Z_]\w*))',
    flags=re.IGNORECASE | re.ASCII,
)
_SQL_DISALLOWED_JOIN_RE = re.compile(r"(?i)\b(?:cross|natural)\s+join\b")
_SQL_LIST_SHEET_TABLES = "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'sheet_%'"


@dataclass(frozen=True)
class TableAsset:
    table_id: str
    document_id: UUID
    sheet_index: int
    sheet_name: str | None
    sql_table: str
    row_count: int
    col_count: int
    truncated: bool
    columns: list[dict[str, Any]]
    sample_rows: list[dict[str, Any]]
    row_source_table: str | None = None
    row_source_sync_token: str | None = None
    row_source_pk_hash_col: str | None = None


@dataclass(frozen=True)
class TableStoreContext:
    tenant_id: UUID
    dataset_id: UUID
    document_id: UUID

    @property
    def store_path(self) -> Path:
        return table_store_path(tenant_id=self.tenant_id, dataset_id=self.dataset_id, document_id=self.document_id)


@dataclass(frozen=True)
class TableImportLimits:
    max_rows: int
    max_cols: int
    sample_rows: int

    @property
    def row_limit(self) -> int:
        return max(0, int(self.max_rows or 0))

    @property
    def col_limit(self) -> int:
        return max(0, int(self.max_cols or 0))


@dataclass(frozen=True)
class SheetWriteOptions:
    sheet_index: int
    sheet_name: str | None
    truncated: bool
    sample_rows: int
    row_source_table: str | None = None
    row_source_sync_token: str | None = None
    row_source_pk_hash_col: str | None = None


@dataclass(frozen=True)
class TableQueryLimits:
    max_rows: int
    max_cols: int
    max_bytes: int

    @property
    def row_limit(self) -> int:
        return max(1, int(self.max_rows or 0))

    @property
    def byte_limit(self) -> int:
        return max(10_000, int(self.max_bytes or 0))


def _sqlite_timeout_sec() -> float:
    """
    Coerce and clamp sqlite busy timeout.

    - Keep requests responsive by capping excessively large values.
    - Allow 0 to fail fast when the DB is locked.
    """
    raw = getattr(settings, "TABLE_STORE_SQLITE_TIMEOUT_SEC", 30.0)
    try:
        timeout = float(raw)  # type: ignore[arg-type]
    except Exception:
        timeout = 30.0

    if timeout < 0:
        timeout = 0.0
    return min(timeout, 120.0)


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
    except Exception as exc:
        logger.debug(_TABLE_STORE_FALLBACK_LOG_MESSAGE, exc)
    return str(v)


def _stable_row_hash(row: dict[str, Any], *, exclude_keys: set[str] | None = None) -> str:
    excluded = {str(k) for k in (exclude_keys or set())}
    payload: dict[str, Any] = {}
    for key in sorted(row.keys()):
        key_s = str(key)
        if key_s in excluded:
            continue
        payload[key_s] = _jsonify_value(row.get(key))
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()


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
    for c in df.columns:
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


def _sanitize_column_name(name: Any, *, idx: int, seen: dict[str, int]) -> str:  # noqa: ANN401
    raw = str(name) if name is not None else ""
    raw = raw.replace("\r", " ").replace("\n", " ")
    raw = _BOM_RE.sub("", raw)
    raw = _WS_RE.sub(" ", raw).strip()
    if not raw:
        raw = f"col_{idx + 1}"
    raw = raw[:200]

    key = raw.casefold()
    count = seen.get(key, 0) + 1
    seen[key] = count
    if count > 1:
        raw = f"{raw}_{count}"
    return raw


def _sanitize_dataframe(df: "pd.DataFrame") -> "pd.DataFrame":
    """
    Ensure DataFrame columns are non-empty and unique.

    This prevents SQLite import failures (duplicate/empty column names) and keeps NL->SQL
    more stable across noisy inputs.
    """
    try:
        cols = list(getattr(df, "columns", []))
    except Exception as exc:
        logger.debug(_TABLE_STORE_FALLBACK_LOG_MESSAGE, exc)
        cols = []

    seen: dict[str, int] = {}
    new_cols = [_sanitize_column_name(c, idx=i, seen=seen) for i, c in enumerate(cols)]
    if not new_cols:
        # SQLite cannot create a table with zero columns. Empty Excel sheets are
        # still valid table assets, so persist a harmless placeholder column.
        try:
            return pd.DataFrame({"__empty__": pd.Series(dtype="object")})
        except Exception as exc:
            logger.debug(_TABLE_STORE_FALLBACK_LOG_MESSAGE, exc)
            return df
    try:
        df.columns = new_cols
    except Exception as exc:
        logger.debug(_TABLE_STORE_FALLBACK_LOG_MESSAGE, exc)
    return df


def _connect_rw(path: Path) -> sqlite3.Connection:
    # Ensure parent directory exists; storage path itself is deterministic (not user-controlled).
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.debug(_TABLE_STORE_FALLBACK_LOG_MESSAGE, exc)
    timeout = _sqlite_timeout_sec()
    conn = sqlite3.connect(str(path), timeout=timeout)
    conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)};")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _connect_ro(path: Path) -> sqlite3.Connection:
    # Read-only query connection (prevents writes even if authorizer is bypassed).
    uri = f"file:{path}?mode=ro"
    timeout = _sqlite_timeout_sec()
    conn = sqlite3.connect(uri, uri=True, timeout=timeout)
    conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)};")
    conn.row_factory = sqlite3.Row
    return conn


def _drop_sheet_tables(path: Path) -> None:
    try:
        conn = _connect_rw(path)
        try:
            cur = conn.execute(_SQL_LIST_SHEET_TABLES)
            for row in cur.fetchall():
                name = str(row[0] or "")
                if name:
                    conn.execute(f"DROP TABLE IF EXISTS {quote_sqlite_ident(name)};")
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug(_TABLE_STORE_FALLBACK_LOG_MESSAGE, exc)


def _reset_table_store(context: TableStoreContext) -> Path:
    out_path = context.store_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if out_path.exists():
            out_path.unlink()
    except Exception as exc:
        logger.debug(_TABLE_STORE_FALLBACK_LOG_MESSAGE, exc)
    if out_path.exists():
        _drop_sheet_tables(out_path)
    return out_path


def import_table_document(  # noqa: PLR0913 - public importer keeps explicit API fields.
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

    context = TableStoreContext(tenant_id=tenant_id, dataset_id=dataset_id, document_id=document_id)
    limits = TableImportLimits(max_rows=max_rows, max_cols=max_cols, sample_rows=sample_rows)
    _reset_table_store(context)

    if ext == ".csv":
        df, truncated = _read_csv(file_path, max_rows=limits.max_rows, max_cols=limits.max_cols)
        df = _sanitize_dataframe(df)
        return _write_single_sheet(
            context=context,
            df=df,
            options=SheetWriteOptions(
                sheet_index=0, sheet_name=None, truncated=truncated, sample_rows=limits.sample_rows
            ),
        )

    # Excel (.xls/.xlsx)
    return _import_excel_from_context(
        context=context,
        file_path=file_path,
        limits=limits,
    )


def _sniff_csv_delimiter(path: Path, *, max_bytes: int = 64_000) -> str | None:
    """
    Best-effort delimiter sniffing for CSV files.

    Pandas' default assumes commas; many enterprise exports use tabs/semicolons.
    """
    try:
        buf = path.read_bytes()[: max(1024, int(max_bytes or 0))]
    except Exception:
        return None

    # Decode best-effort; delimiter characters are ASCII.
    sample = buf.decode("utf-8", errors="ignore")
    if not sample.strip():
        return None

    # Avoid expensive sniff on huge samples.
    sample = sample[:32_000]
    try:
        import csv

        sniffed = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delim = str(getattr(sniffed, "delimiter", "") or "")
        return delim if delim in {",", "\t", ";", "|"} else None
    except Exception:
        return None


def _read_csv(path: Path, *, max_rows: int, max_cols: int) -> tuple["pd.DataFrame", bool]:
    hard_nrows = max(0, int(max_rows or 0))
    # Read one extra row so we can accurately set `truncated` without loading the entire file.
    nrows = (hard_nrows + 1) if hard_nrows > 0 else None
    kwargs: dict[str, Any] = {"dtype_backend": "numpy_nullable", "encoding_errors": "replace"}
    delim = _sniff_csv_delimiter(path)
    if delim:
        kwargs["sep"] = delim
        kwargs["engine"] = "python"

    df = pd.read_csv(str(path), nrows=nrows, **kwargs)  # type: ignore[call-arg]
    truncated = False
    if hard_nrows > 0 and int(getattr(df, "shape", (0, 0))[0]) > hard_nrows:
        truncated = True
        df = df.head(hard_nrows)
    if max_cols and int(max_cols) > 0 and int(getattr(df, "shape", (0, 0))[1]) > int(max_cols):
        df = df.iloc[:, : int(max_cols)]
    return df, truncated


def _excel_sheet_names(xls: Any) -> list[str]:
    try:
        return list(getattr(xls, "sheet_names", []) or [])
    except Exception:
        return []


def _bounded_excel_sheet_names(sheet_names: list[str]) -> tuple[list[str], bool]:
    max_sheets = int(getattr(settings, "TABLE_STORE_MAX_SHEETS", 0) or 0)
    if max_sheets > 0 and len(sheet_names) > max_sheets:
        return sheet_names[: max(0, int(max_sheets))], True
    return sheet_names, False


def _read_excel_sheet(
    xls: Any, *, sheet_name: str, limits: TableImportLimits, workbook_truncated: bool
) -> tuple["pd.DataFrame", bool] | None:
    hard_nrows = limits.row_limit
    nrows = (hard_nrows + 1) if hard_nrows > 0 else None
    try:
        df = pd.read_excel(xls, sheet_name=sheet_name, nrows=nrows, dtype_backend="numpy_nullable")  # type: ignore[call-arg]
    except Exception:
        get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
        return None

    truncated = bool(workbook_truncated)
    if hard_nrows > 0 and int(getattr(df, "shape", (0, 0))[0]) > hard_nrows:
        truncated = True
        df = df.head(hard_nrows)
    if limits.col_limit > 0 and int(getattr(df, "shape", (0, 0))[1]) > limits.col_limit:
        df = df.iloc[:, : limits.col_limit]
    return _sanitize_dataframe(df), truncated


def _write_empty_sheet(context: TableStoreContext, *, sample_rows: int) -> list[TableAsset]:
    return _write_single_sheet(
        context=context,
        df=pd.DataFrame(),
        options=SheetWriteOptions(sheet_index=0, sheet_name=None, truncated=False, sample_rows=sample_rows),
    )


def _import_excel(  # noqa: PLR0913 - retained for direct private-call compatibility in tests/tools.
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
    file_path: Path,
    max_rows: int,
    max_cols: int,
    sample_rows: int,
) -> list[TableAsset]:
    return _import_excel_from_context(
        context=TableStoreContext(tenant_id=tenant_id, dataset_id=dataset_id, document_id=document_id),
        file_path=file_path,
        limits=TableImportLimits(max_rows=max_rows, max_cols=max_cols, sample_rows=sample_rows),
    )


def _import_excel_from_context(
    *,
    context: TableStoreContext,
    file_path: Path,
    limits: TableImportLimits,
) -> list[TableAsset]:
    # Keep this simple and robust: use pandas for both .xls and .xlsx.
    #
    # Important: ensure the underlying file handle is closed, otherwise Windows
    # can fail to delete temp xlsx files during cleanup (PermissionError).
    try:
        with pd.ExcelFile(str(file_path)) as xls:
            assets: list[TableAsset] = []
            sheet_names, workbook_truncated = _bounded_excel_sheet_names(_excel_sheet_names(xls))

            if not sheet_names:
                # Produce an empty sheet0 table for consistency.
                return _write_empty_sheet(context, sample_rows=limits.sample_rows)

            for idx, name in enumerate(sheet_names):
                read = _read_excel_sheet(xls, sheet_name=name, limits=limits, workbook_truncated=workbook_truncated)
                if read is None:
                    continue
                df, truncated = read
                assets.extend(
                    _write_single_sheet(
                        context=context,
                        df=df,
                        options=SheetWriteOptions(
                            sheet_index=int(idx),
                            sheet_name=str(name),
                            truncated=truncated,
                            sample_rows=limits.sample_rows,
                        ),
                    )
                )

            return assets or []
    except Exception as exc:
        hint = ""
        ext = file_path.suffix.lower()
        if ext == ".xls":
            hint = " (hint: install 'xlrd' for .xls support)"
        if ext == ".xlsx":
            hint = " (hint: install 'openpyxl' for .xlsx support)"
        raise RuntimeError(f"excel_open_failed{hint}: {str(exc)[:200]}") from exc


def _write_single_sheet(
    *,
    context: TableStoreContext,
    df: "pd.DataFrame",
    options: SheetWriteOptions,
) -> list[TableAsset]:
    out_path = context.store_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sql_table = sql_table_name_for_sheet(options.sheet_index)
    table_id = format_table_id(document_id=context.document_id, sheet_index=options.sheet_index)

    conn = _connect_rw(out_path)
    try:
        # Replace the sheet table.
        conn.execute(f"DROP TABLE IF EXISTS {quote_sqlite_ident(sql_table)};")
        # Use pandas to write; it will create columns with proper quoting.
        df = _sanitize_dataframe(df)
        df.to_sql(sql_table, conn, if_exists="replace", index=False)
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception as exc:
            logger.debug(_TABLE_STORE_FALLBACK_LOG_MESSAGE, exc)

    rows = int(getattr(df, "shape", (0, 0))[0])
    cols = int(getattr(df, "shape", (0, 0))[1])

    asset = TableAsset(
        table_id=table_id,
        document_id=context.document_id,
        sheet_index=int(options.sheet_index),
        sheet_name=(options.sheet_name if options.sheet_name else None),
        sql_table=sql_table,
        row_count=rows,
        col_count=cols,
        truncated=bool(options.truncated),
        columns=_df_columns(df),
        sample_rows=_df_sample_rows(df, sample_rows=options.sample_rows),
        row_source_table=(str(options.row_source_table).strip() if options.row_source_table else None),
        row_source_sync_token=(str(options.row_source_sync_token).strip() if options.row_source_sync_token else None),
        row_source_pk_hash_col=(
            str(options.row_source_pk_hash_col).strip() if options.row_source_pk_hash_col else None
        ),
    )
    return [asset]


def _docx_block_text(block: Any, doc: Any) -> str:
    from docx.text.paragraph import Paragraph  # type: ignore

    paragraph = Paragraph(block, doc)
    text = str(getattr(paragraph, "text", "") or "").replace("\r", " ").replace("\n", " ")
    return _WS_RE.sub(" ", text).strip()


def _append_docx_lookback(prev_paras: list[str], text: str) -> list[str]:
    if not text:
        return prev_paras
    updated = [*prev_paras, text]
    return updated[-3:]


def _docx_table_sheet_name(prev_paras: list[str], table_index: int) -> str:
    for candidate in reversed(prev_paras[-2:]):
        if len(candidate) <= 200 and _DOCX_TABLE_CAPTION_RE.match(candidate):
            return candidate
    return f"Table {int(table_index) + 1}"


def _docx_cell_text(cell: Any) -> str:
    text = str(getattr(cell, "text", "") or "").replace("\r", " ").replace("\n", " ")
    return _WS_RE.sub(" ", text).strip()


def _docx_table_rows(table: Any, *, max_rows: int) -> tuple[list[list[str]], bool]:
    raw_rows: list[list[str]] = []
    truncated = False
    for row in getattr(table, "rows", []) or []:
        cells = [_docx_cell_text(cell) for cell in (getattr(row, "cells", []) or [])]
        if any(cells):
            raw_rows.append(cells)
        if max_rows > 0 and len(raw_rows) >= max_rows:
            truncated = True
            break
    return raw_rows, truncated


def _docx_padded_rows(raw_rows: list[list[str]], *, max_cols: int) -> list[list[str]]:
    width = max((len(row) for row in raw_rows), default=0)
    if max_cols > 0:
        width = min(width, max_cols)
    width = max(1, int(width))
    return [(list(row) + [""] * max(0, width - len(row)))[:width] for row in raw_rows]


def _docx_row_looks_like_header(padded: list[list[str]]) -> bool:
    if len(padded) < 2:
        return False
    header = padded[0]
    width = max(1, len(header))
    non_empty = [cell for cell in header if str(cell or "").strip()]
    if len(non_empty) < max(1, width // 2):
        return False
    keys = [str(cell).strip().casefold() for cell in non_empty]
    numeric = sum(1 for cell in non_empty if _NUMERIC_ONLY_RE.match(str(cell or "")))
    avg_len = sum(len(str(cell)) for cell in non_empty) / max(1, len(non_empty))
    return len(set(keys)) == len(keys) and numeric <= max(1, len(non_empty) // 3) and avg_len <= 40


def _docx_dataframe_from_rows(raw_rows: list[list[str]], *, max_cols: int) -> "pd.DataFrame | None":
    if not raw_rows:
        return None
    padded = _docx_padded_rows(raw_rows, max_cols=max_cols)
    if _docx_row_looks_like_header(padded):
        col_names = padded[0]
        body_rows = padded[1:]
    else:
        col_names = [f"col_{i + 1}" for i in range(len(padded[0]))]
        body_rows = padded
    return _sanitize_dataframe(pd.DataFrame(body_rows, columns=col_names))


def import_docx_tables(  # noqa: PLR0913 - public importer keeps explicit API fields.
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
    Best-effort: extract DOCX tables into the per-document SQLite table store.

    Notes:
    - This does NOT handle DOCX paragraphs; it only imports tables.
    - Intended to be used as a sidecar feature (keep RAG chunking untouched).
    """
    ext = file_path.suffix.lower()
    if ext != ".docx":
        raise ValueError("unsupported docx file type")

    context = TableStoreContext(tenant_id=tenant_id, dataset_id=dataset_id, document_id=document_id)
    limits = TableImportLimits(max_rows=max_rows, max_cols=max_cols, sample_rows=sample_rows)
    _reset_table_store(context)

    from docx import Document as DocxDocument  # type: ignore

    doc = DocxDocument(str(file_path))

    # Walk blocks in document order so we can infer a reasonable `sheet_name` from nearby
    # paragraphs (e.g. "Table 1: ..." captions).
    from docx.oxml.table import CT_Tbl  # type: ignore
    from docx.oxml.text.paragraph import CT_P  # type: ignore
    from docx.table import Table  # type: ignore

    body = getattr(getattr(doc, "element", None), "body", None)
    children = list(body.iterchildren()) if body is not None else []

    max_sheets = int(getattr(settings, "TABLE_STORE_MAX_SHEETS", 0) or 0)

    prev_paras: list[str] = []
    assets: list[TableAsset] = []
    table_index = 0

    for child in children:
        if max_sheets > 0 and table_index >= max_sheets:
            break

        if isinstance(child, CT_P):
            prev_paras = _append_docx_lookback(prev_paras, _docx_block_text(child, doc))
            continue

        if not isinstance(child, CT_Tbl):
            continue

        table = Table(child, doc)
        raw_rows, truncated = _docx_table_rows(table, max_rows=limits.row_limit)
        df = _docx_dataframe_from_rows(raw_rows, max_cols=limits.col_limit)
        if df is None:
            continue

        assets.extend(
            _write_single_sheet(
                context=context,
                df=df,
                options=SheetWriteOptions(
                    sheet_index=int(table_index),
                    sheet_name=_docx_table_sheet_name(prev_paras, table_index),
                    truncated=bool(truncated),
                    sample_rows=limits.sample_rows,
                ),
            )
        )
        table_index += 1
        # Captions are usually adjacent to a table; avoid reusing old captions for
        # back-to-back tables with no intervening paragraphs.
        prev_paras = []

    return assets


def _extract_markdown_table_blocks(text: str) -> list[list[str]]:
    """
    Best-effort: extract pipe-table blocks from markdown-like text.

    We keep this conservative (line-based) since this is used on parser-emitted table segments,
    not arbitrary user-provided markdown.
    """
    raw = str(text or "")
    if not raw.strip():
        return []

    blocks: list[list[str]] = []
    current: list[str] = []

    for line in raw.splitlines():
        s = line.strip()
        looks_like_table = bool(s.startswith("|") and "|" in s)
        if looks_like_table:
            current.append(line)
            continue
        if current:
            blocks.append(current)
            current = []

    if current:
        blocks.append(current)

    return blocks


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [part.replace(r"\|", "|").strip() for part in stripped.split("|")]


def _markdown_table_body_start(lines: list[str], header_width: int) -> tuple[int, bool]:
    separator = _split_markdown_table_row(lines[1]) if len(lines) >= 2 else []
    if (
        separator
        and len(separator) == header_width
        and all(_MD_TABLE_SEP_CELL_RE.match(cell or "") for cell in separator)
    ):
        return 2, True
    return 1, False


def _parse_markdown_table(block_lines: list[str]) -> tuple["pd.DataFrame", bool] | None:
    """
    Best-effort: parse a GitHub-flavored markdown table into a DataFrame.

    Returns: (df, had_separator_row) or None if it doesn't look like a table.
    """
    lines = [str(line or "") for line in (block_lines or []) if str(line or "").strip()]
    if len(lines) < 2:
        return None

    header = _split_markdown_table_row(lines[0])
    if not any(header):
        return None

    body_start, had_sep = _markdown_table_body_start(lines, len(header))

    rows: list[list[str]] = []
    for line in lines[body_start:]:
        row = _split_markdown_table_row(line)
        if not any(row):
            continue
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))
        if len(row) > len(header):
            row = row[: len(header)]
        rows.append(row)

    df = pd.DataFrame(rows, columns=[str(c) for c in header])
    return df, had_sep


def import_markdown_tables(  # noqa: PLR0913 - public importer keeps explicit API fields.
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
    tables: list[dict[str, Any]],
    max_rows: int,
    max_cols: int,
    sample_rows: int,
) -> list[TableAsset]:
    """
    Best-effort: import parsed markdown tables into the per-document Table Store (SQLite).

    Input format:
      tables: [{"markdown": "...", "sheet_name": "optional label"}, ...]
    """
    context = TableStoreContext(tenant_id=tenant_id, dataset_id=dataset_id, document_id=document_id)
    _reset_table_store(context)

    max_rows_i = max(0, int(max_rows or 0))
    max_cols_i = max(0, int(max_cols or 0))
    max_sheets = int(getattr(settings, "TABLE_STORE_MAX_SHEETS", 0) or 0)

    assets: list[TableAsset] = []
    sheet_index = 0

    for t in tables or []:
        if not isinstance(t, dict):
            continue
        md = str(t.get("markdown") or "")
        if not md.strip():
            continue

        sheet_name = t.get("sheet_name")
        sheet_name = str(sheet_name) if sheet_name is not None else None

        for block in _extract_markdown_table_blocks(md):
            parsed = _parse_markdown_table(block)
            if parsed is None:
                continue
            df, _had_sep = parsed
            df = _sanitize_dataframe(df)

            truncated = False
            if max_rows_i > 0 and int(getattr(df, "shape", (0, 0))[0]) > max_rows_i:
                truncated = True
                df = df.head(max_rows_i)
            if max_cols_i > 0 and int(getattr(df, "shape", (0, 0))[1]) > max_cols_i:
                truncated = True
                df = df.iloc[:, :max_cols_i]

            assets.extend(
                _write_single_sheet(
                    context=context,
                    df=df,
                    options=SheetWriteOptions(
                        sheet_index=int(sheet_index),
                        sheet_name=sheet_name,
                        truncated=truncated,
                        sample_rows=sample_rows,
                    ),
                )
            )
            sheet_index += 1
            if max_sheets > 0 and sheet_index >= max_sheets:
                break

        if max_sheets > 0 and sheet_index >= max_sheets:
            break

    return assets


def _db_snapshot_column_name(raw: Any) -> str:
    if isinstance(raw, dict):
        return str(raw.get("name") or "").strip()
    return str(raw or "").strip()


def _db_snapshot_column_names(snap: dict[str, Any], *, max_cols: int) -> list[str]:
    cols_raw = snap.get("columns")
    if not isinstance(cols_raw, list):
        return []
    column_names: list[str] = []
    for raw in cols_raw:
        name = _db_snapshot_column_name(raw)
        if not name:
            continue
        column_names.append(name)
        if max_cols > 0 and len(column_names) >= max_cols:
            break
    return column_names


def _db_snapshot_rows(
    snap: dict[str, Any],
    *,
    column_names: list[str],
    pk_hash_col: str,
    max_rows: int,
) -> list[dict[str, Any]]:
    rows_raw = snap.get("rows") if isinstance(snap.get("rows"), list) else []
    rows_norm: list[dict[str, Any]] = []
    for row in rows_raw:
        if max_rows > 0 and len(rows_norm) >= max_rows:
            break
        if not isinstance(row, dict):
            continue
        rec_raw: dict[str, Any] = {str(k): _jsonify_value(v) for k, v in row.items()}
        rec = {key: rec_raw.get(key) for key in column_names} if column_names else dict(rec_raw)
        if pk_hash_col not in rec and pk_hash_col in rec_raw:
            rec[pk_hash_col] = rec_raw.get(pk_hash_col)
        rows_norm.append(rec)
    return rows_norm


def _db_snapshot_final_columns(
    *,
    column_names: list[str],
    rows_norm: list[dict[str, Any]],
    pk_hash_col: str,
    max_cols: int,
) -> list[str]:
    if not column_names and rows_norm:
        column_names = [str(key) for key in rows_norm[0].keys()]
        if max_cols > 0:
            column_names = column_names[:max_cols]
    if pk_hash_col not in column_names and (max_cols <= 0 or len(column_names) < max_cols):
        column_names.append(pk_hash_col)
    return column_names or [pk_hash_col]


def _db_snapshot_dataframe(snap: dict[str, Any], *, max_rows: int, max_cols: int) -> tuple["pd.DataFrame", str]:
    pk_hash_col = str(snap.get("source_pk_hash_col") or "__row_pk_hash").strip() or "__row_pk_hash"
    column_names = _db_snapshot_column_names(snap, max_cols=max_cols)
    rows_norm = _db_snapshot_rows(snap, column_names=column_names, pk_hash_col=pk_hash_col, max_rows=max_rows)
    column_names = _db_snapshot_final_columns(
        column_names=column_names,
        rows_norm=rows_norm,
        pk_hash_col=pk_hash_col,
        max_cols=max_cols,
    )
    for rec in rows_norm:
        if not rec.get(pk_hash_col):
            rec[pk_hash_col] = _stable_row_hash(rec, exclude_keys={pk_hash_col})
    clipped_rows = [{name: rec.get(name) for name in column_names} for rec in rows_norm]
    return _sanitize_dataframe(pd.DataFrame(clipped_rows, columns=column_names)), pk_hash_col


def _db_snapshot_write_options(
    snap: dict[str, Any], *, idx: int, sample_rows: int, pk_hash_col: str
) -> SheetWriteOptions:
    fallback_name = f"table_{idx + 1}"
    sheet_name = str(snap.get("sheet_name") or snap.get("source_table") or fallback_name).strip()[:200] or fallback_name
    return SheetWriteOptions(
        sheet_index=int(idx),
        sheet_name=sheet_name,
        truncated=False,
        sample_rows=sample_rows,
        row_source_table=str(snap.get("source_table") or "").strip() or None,
        row_source_sync_token=str(snap.get("source_sync_token") or "").strip() or None,
        row_source_pk_hash_col=pk_hash_col,
    )


def import_db_row_snapshots(  # noqa: PLR0913 - public importer keeps explicit API fields.
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
    snapshots: list[dict[str, Any]],
    max_tables: int,
    max_rows_per_table: int,
    max_cols: int,
    sample_rows: int,
) -> list[TableAsset]:
    """
    Import bounded DB row snapshots into per-document Table Store.

    Expected snapshot item (best-effort):
      {
        "sheet_name": "demo.users",
        "source_table": "demo.users",
        "source_sync_token": "tok-...",
        "source_pk_hash_col": "__row_pk_hash",   # optional
        "columns": ["id", "name"],               # optional
        "rows": [{"id": 1, "name": "alice"}, ...]
      }
    """
    context = TableStoreContext(tenant_id=tenant_id, dataset_id=dataset_id, document_id=document_id)
    _reset_table_store(context)

    max_tables_i = max(0, int(max_tables or 0))
    max_rows_i = max(0, int(max_rows_per_table or 0))
    max_cols_i = max(0, int(max_cols or 0))

    assets: list[TableAsset] = []
    for idx, snap in enumerate(snapshots or []):
        if max_tables_i > 0 and idx >= max_tables_i:
            break
        if not isinstance(snap, dict):
            continue

        df, pk_hash_col = _db_snapshot_dataframe(snap, max_rows=max_rows_i, max_cols=max_cols_i)
        assets.extend(
            _write_single_sheet(
                context=context,
                df=df,
                options=_db_snapshot_write_options(snap, idx=idx, sample_rows=sample_rows, pk_hash_col=pk_hash_col),
            )
        )

    return assets


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
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
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
                row_source_table=(str(t.get("row_source_table") or "").strip() or None),
                row_source_sync_token=(str(t.get("row_source_sync_token") or "").strip() or None),
                row_source_pk_hash_col=(str(t.get("row_source_pk_hash_col") or "").strip() or None),
            )
        )
    return out


def _extract_sql_table_refs(sql: str) -> list[str]:
    refs: list[str] = []
    for m in _SQL_TABLE_REF_RE.finditer(str(sql or "")):
        raw = str((m.group(1) or m.group(2) or "")).strip()
        if not raw:
            continue
        if raw.startswith("("):
            continue
        if raw not in refs:
            refs.append(raw)
    return refs


def evaluate_planner_execution_mismatch(
    *,
    planner_diagnostics: dict[str, Any] | None,
    expected_sql_fingerprint: str | None,
    executed_sql: str,
) -> dict[str, Any]:
    planner = planner_diagnostics if isinstance(planner_diagnostics, dict) else {}
    expected_fp = str(expected_sql_fingerprint or planner.get("sql_fingerprint") or "").strip()
    actual_fp = fingerprint_sql(str(executed_sql or ""), length=16)
    mismatch_reasons: list[str] = []

    expected_tables = [str(v).strip() for v in (planner.get("selected_tables") or []) if str(v).strip()]
    actual_tables = _extract_sql_table_refs(str(executed_sql or ""))

    if expected_fp and actual_fp and expected_fp != actual_fp:
        mismatch_reasons.append("sql_fingerprint_mismatch")
    if expected_tables:
        expected_set = set(expected_tables)
        actual_set = set(actual_tables)
        if actual_set and not actual_set.issubset(expected_set):
            mismatch_reasons.append("sql_table_set_mismatch")

    return {
        "expected_sql_fingerprint": expected_fp or None,
        "actual_sql_fingerprint": actual_fp or None,
        "expected_tables": expected_tables,
        "actual_tables": actual_tables,
        "mismatch": bool(mismatch_reasons),
        "reasons": list(islice(mismatch_reasons, 8)),
    }


def _clamped_table_query_limits(*, max_rows: int, max_cols: int, max_bytes: int) -> TableQueryLimits:
    hard_rows = int(getattr(settings, "TABLE_QUERY_MAX_ROWS", 0) or 0)
    hard_cols = int(getattr(settings, "TABLE_QUERY_MAX_COLS", 0) or 0)
    hard_bytes = int(getattr(settings, "TABLE_QUERY_MAX_BYTES", 0) or 0)
    if hard_rows > 0:
        max_rows = min(int(max_rows or 0) or hard_rows, hard_rows)
    if hard_cols > 0:
        max_cols = min(int(max_cols or 0) or hard_cols, hard_cols)
    if hard_bytes > 0:
        max_bytes = min(int(max_bytes or 0) or hard_bytes, hard_bytes)
    return TableQueryLimits(max_rows=max_rows, max_cols=max_cols, max_bytes=max_bytes)


def _validate_table_query_sql(raw_sql: str) -> None:
    if not raw_sql.strip():
        raise ValueError("sql is required")
    max_sql_chars = int(getattr(settings, "TABLE_QUERY_MAX_SQL_CHARS", 20_000) or 20_000)
    if max_sql_chars > 0 and len(raw_sql) > int(max_sql_chars):
        raise ValueError(f"sql_too_long (max {int(max_sql_chars)})")
    if ";" in raw_sql:
        raise ValueError("multiple statements are not allowed")
    if not _SQL_SELECT_PREFIX_RE.match(raw_sql):
        raise ValueError("only SELECT queries are allowed")
    if re.search(r"\bsqlite_(?:master|schema|temp_master|temp_schema)\b", raw_sql, flags=re.IGNORECASE):
        raise ValueError("schema_table_reference_not_allowed")


def _normalize_table_query_sql(raw_sql: str, *, limit: int) -> str:
    normalized = raw_sql.strip()
    if re.search(r"\blimit\b", normalized, flags=re.IGNORECASE) is None:
        return f"{normalized}\nLIMIT {limit}"

    try:
        limits = [int(match.group(1)) for match in re.finditer(r"\blimit\s+(\d+)\b", normalized, flags=re.IGNORECASE)]
    except Exception:
        limits = []
    if limits and max(limits) > limit:
        raise ValueError(f"limit_too_large (max {limit})")
    return normalized


def _query_allowed_tables(*, sql_table: str, allowed_sql_tables: list[str] | None) -> set[str]:
    allowed_tables = {sql_table}
    for raw in allowed_sql_tables or []:
        name = str(raw or "").strip()
        if name:
            allowed_tables.add(name)
    return allowed_tables


def _validate_query_table_refs(normalized_sql: str, *, allowed_tables: set[str]) -> None:
    if _SQL_DISALLOWED_JOIN_RE.search(normalized_sql) and not bool(
        getattr(settings, "TABLE_QUERY_ALLOW_CROSS_JOIN", False)
    ):
        raise ValueError("join_type_not_allowed")

    referenced_tables = _extract_sql_table_refs(normalized_sql)
    if not referenced_tables:
        return
    max_join_tables = int(getattr(settings, "TABLE_QUERY_MAX_JOIN_TABLES", 4) or 4)
    if max_join_tables > 0 and len(set(referenced_tables)) > max_join_tables:
        raise ValueError(f"too_many_join_tables (max {max_join_tables})")
    if any(table not in allowed_tables for table in referenced_tables):
        raise ValueError("table_reference_not_allowed")


def _query_timeout_settings() -> tuple[float, int]:
    return (
        float(getattr(settings, "TABLE_QUERY_TIMEOUT_SEC", 0.0) or 0.0),
        int(getattr(settings, "TABLE_QUERY_PROGRESS_OPS", 0) or 0),
    )


def _install_query_progress_handler(conn: sqlite3.Connection, *, timeout_sec: float, progress_ops: int) -> None:
    if timeout_sec <= 0 or progress_ops <= 0:
        return
    start = time.monotonic()

    def _progress() -> int:  # pragma: no cover (timing dependent)
        return 1 if (time.monotonic() - start) > timeout_sec else 0

    try:
        conn.set_progress_handler(_progress, int(progress_ops))
    except Exception as exc:
        logger.debug(_TABLE_STORE_FALLBACK_LOG_MESSAGE, exc)


def _limited_query_columns(cur: sqlite3.Cursor, *, max_cols: int) -> tuple[list[str], bool]:
    col_names = [description[0] for description in (cur.description or [])]
    if max_cols and int(max_cols) > 0 and len(col_names) > int(max_cols):
        return col_names[: int(max_cols)], True
    return col_names, False


def _fetch_query_rows(
    cur: sqlite3.Cursor, *, col_names: list[str], limits: TableQueryLimits
) -> tuple[list[list[Any]], bool]:
    out_rows: list[list[Any]] = []
    bytes_used = 0
    truncated = False
    for row in cur.fetchmany(limits.row_limit + 1):
        if len(out_rows) >= limits.row_limit:
            truncated = True
            break
        values = list(row)[: len(col_names)]
        out_rows.append([_jsonify_value(value) for value in values])
        try:
            bytes_used += len(json.dumps(out_rows[-1], ensure_ascii=False))
        except Exception:
            bytes_used += 0
        if bytes_used > limits.byte_limit:
            truncated = True
            break
    return out_rows, truncated


def _execute_table_query(
    conn: sqlite3.Connection,
    *,
    normalized_sql: str,
    limits: TableQueryLimits,
    timeout_sec: float,
) -> dict[str, Any]:
    try:
        cur = conn.execute(normalized_sql)
    except sqlite3.OperationalError as exc:
        msg = str(exc or "").lower()
        if "interrupted" in msg and timeout_sec > 0:
            raise TimeoutError(f"query_timeout ({timeout_sec:.1f}s)") from exc
        raise

    col_names, truncated_cols = _limited_query_columns(cur, max_cols=limits.max_cols)
    out_rows, truncated_rows = _fetch_query_rows(cur, col_names=col_names, limits=limits)
    return {"columns": col_names, "rows": out_rows, "truncated": bool(truncated_cols or truncated_rows)}


def run_table_query(  # noqa: PLR0913 - public query API keeps explicit guardrail fields.
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    table_id: str,
    sql: str,
    max_rows: int,
    max_cols: int,
    max_bytes: int,
    allowed_sql_tables: list[str] | None = None,
    planner_diagnostics: dict[str, Any] | None = None,
    expected_sql_fingerprint: str | None = None,
) -> dict[str, Any]:
    """
    Execute a SELECT-only query against a single table within a document store.

    Returns: {columns: [...], rows: [...], truncated: bool, sql: "..."}
    """
    parsed = parse_table_id(table_id)
    if parsed is None:
        raise ValueError("invalid table_id")

    raw_sql = str(sql or "")
    limits = _clamped_table_query_limits(max_rows=max_rows, max_cols=max_cols, max_bytes=max_bytes)
    _validate_table_query_sql(raw_sql)

    sql_table = sql_table_name_for_sheet(parsed.sheet_index)
    db_path = table_store_path(tenant_id=tenant_id, dataset_id=dataset_id, document_id=parsed.document_id)
    if not db_path.exists():
        raise FileNotFoundError("table store not found")

    normalized = _normalize_table_query_sql(raw_sql, limit=limits.row_limit)
    allowed_tables = _query_allowed_tables(sql_table=sql_table, allowed_sql_tables=allowed_sql_tables)
    _validate_query_table_refs(normalized, allowed_tables=allowed_tables)

    # SQLite authorizer: deny writes/pragma/attach and restrict reads to our sheet table only.
    conn = _connect_ro(db_path)
    try:
        timeout_sec, progress_ops = _query_timeout_settings()
        _install_query_progress_handler(conn, timeout_sec=timeout_sec, progress_ops=progress_ops)
        _apply_sqlite_readonly_authorizer(conn, allowed_tables=allowed_tables)
        result = _execute_table_query(conn, normalized_sql=normalized, limits=limits, timeout_sec=timeout_sec)
        planner_mismatch = evaluate_planner_execution_mismatch(
            planner_diagnostics=planner_diagnostics,
            expected_sql_fingerprint=expected_sql_fingerprint,
            executed_sql=normalized,
        )
        return {
            "columns": result["columns"],
            "rows": result["rows"],
            "truncated": bool(result["truncated"]),
            "sql": normalized,
            "planner_execution_mismatch": planner_mismatch,
        }
    finally:
        try:
            conn.close()
        except Exception as exc:
            logger.debug(_TABLE_STORE_FALLBACK_LOG_MESSAGE, exc)


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
