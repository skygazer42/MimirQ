"""
Table routing (RAG vs TAG) helpers.

Goal
----
When `table_store_enabled=true`, we can either:
- import tables into per-document SQLite store (TAG / SQL workflows), or
- fall back to normal parsing + chunking + indexing (RAG),
depending on table size/complexity.

This module implements a conservative, dependency-light *auto route* decision:
- CSV: estimate rows from a bounded byte sample; estimate cols from the first non-empty row.
- XLSX: read workbook metadata (sheet_count, max_row, max_column) via openpyxl read-only mode.
- XLS: best-effort (often requires optional engines); fall back to file-size only.

The decision is explainable (route + reason + stats) and safe (bounded reads).
"""

import csv
import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from app.core.optional_deps import optional_import
from app.rag.core.logging import get_logger

logger = get_logger("services.table_routing")


@lru_cache(maxsize=1)
def _get_openpyxl() -> ModuleType | None:
    return optional_import("openpyxl", feature="table_routing_xlsx_shape")


Route = Literal["rag", "tag"]


@dataclass(frozen=True)
class TableRouteDecision:
    route: Route
    reason: str
    stats: dict[str, Any]


def _safe_stat_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except Exception:
        return 0


def _estimate_csv_shape(path: Path, *, sample_bytes: int) -> tuple[int, int, bool]:
    """
    Returns (rows_est, cols_est, estimated_rows).
    """
    size = _safe_stat_size(path)
    sample_n = max(1024, sample_bytes)
    read_n = min(size, sample_n) if size > 0 else sample_n

    try:
        with path.open("rb") as f:
            buf = f.read(read_n)
    except Exception:
        return 0, 0, True

    # Decode best-effort; we only need rough delimiters/line counts.
    text = buf.decode("utf-8", errors="ignore")
    if not text.strip():
        return 0, 0, bool(size > read_n)

    # Row count: newline count (+1 if last line not endswith \n).
    line_count = text.count("\n")
    if text and not text.endswith("\n"):
        line_count += 1
    estimated_rows = size > read_n
    rows_est = line_count
    if estimated_rows:
        ratio = float(size) / float(max(1, read_n))
        rows_est = int(rows_est * ratio)

    # Column count: sniff delimiter and parse first non-empty row.
    cols_est = 0
    try:
        sample = text[:8192]
        dialect = csv.excel
        try:
            sniffed = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            dialect = sniffed
        except Exception:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)
        for row in reader:
            if row and any(c.strip() for c in row):
                cols_est = len(row)
                break
    except Exception:
        cols_est = 0

    return max(0, rows_est), max(0, cols_est), estimated_rows


def _estimate_xlsx_shape(path: Path, *, max_sheets: int = 20) -> tuple[int, int, int, bool, str | None]:
    """
    Returns (max_rows, max_cols, sheet_count, ok, degraded_reason).
    """
    openpyxl = _get_openpyxl()
    if openpyxl is None:
        return 0, 0, 0, False, "dependency_missing:openpyxl (pip install openpyxl)"

    wb = None
    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        sheetnames = wb.sheetnames
        sheet_count = len(sheetnames)
        max_rows = 0
        max_cols = 0
        for name in sheetnames[: max(1, min(max_sheets, sheet_count))]:
            ws = wb[name]
            r = int(getattr(ws, "max_row", 0) or 0)
            c = int(getattr(ws, "max_column", 0) or 0)
            max_rows = max(max_rows, r)
            max_cols = max(max_cols, c)
        return max_rows, max_cols, sheet_count, True, None
    except Exception:
        return 0, 0, 0, False, "shape_read_failed"
    finally:
        try:
            if wb is not None:
                wb.close()
        except Exception as exc:
            logger.debug("Ignoring workbook close failure during table routing: %s", exc)


def _route_for_csv(
    *,
    file_path: Path,
    stats: dict[str, Any],
    row_threshold: int,
    col_threshold: int,
    csv_sample_bytes: int,
) -> TableRouteDecision:
    rows_est, cols_est, estimated_rows = _estimate_csv_shape(file_path, sample_bytes=csv_sample_bytes)
    stats.update(
        {
            "rows": rows_est,
            "cols": cols_est,
            "estimated_rows": estimated_rows,
            "row_threshold": row_threshold,
            "col_threshold": col_threshold,
        }
    )
    if row_threshold > 0 and rows_est >= row_threshold:
        stats["trigger"] = "rows"
        return TableRouteDecision(route="tag", reason="rows_threshold", stats=stats)
    if col_threshold > 0 and cols_est >= col_threshold:
        stats["trigger"] = "cols"
        return TableRouteDecision(route="tag", reason="cols_threshold", stats=stats)
    return TableRouteDecision(route="rag", reason="below_threshold", stats=stats)


def _route_for_xlsx(
    *,
    file_path: Path,
    stats: dict[str, Any],
    row_threshold: int,
    col_threshold: int,
    sheet_threshold: int,
) -> TableRouteDecision:
    max_rows, max_cols, sheet_count, ok, degraded_reason = _estimate_xlsx_shape(file_path)
    stats.update(
        {
            "rows": max_rows,
            "cols": max_cols,
            "sheet_count": sheet_count,
            "row_threshold": row_threshold,
            "col_threshold": col_threshold,
            "sheet_threshold": sheet_threshold,
            "shape_ok": ok,
        }
    )
    if degraded_reason:
        stats["degraded_reason"] = degraded_reason
    if ok:
        if sheet_threshold > 0 and sheet_count >= sheet_threshold:
            stats["trigger"] = "sheets"
            return TableRouteDecision(route="tag", reason="sheet_threshold", stats=stats)
        if row_threshold > 0 and max_rows >= row_threshold:
            stats["trigger"] = "rows"
            return TableRouteDecision(route="tag", reason="rows_threshold", stats=stats)
        if col_threshold > 0 and max_cols >= col_threshold:
            stats["trigger"] = "cols"
            return TableRouteDecision(route="tag", reason="cols_threshold", stats=stats)
        return TableRouteDecision(route="rag", reason="below_threshold", stats=stats)
    return TableRouteDecision(route="rag", reason="shape_unknown", stats=stats)


def decide_table_route(
    file_path: Path,
    *,
    auto_route: bool,
    file_bytes_threshold: int,
    row_threshold: int,
    col_threshold: int,
    sheet_threshold: int,
    csv_sample_bytes: int = 2_000_000,
) -> TableRouteDecision:
    """
    Decide whether a table-like document should go to TAG (table_store) or RAG.

    If `auto_route` is False, this always returns TAG (backwards compatible).
    """
    ext = file_path.suffix.lower()
    size = _safe_stat_size(file_path)

    stats: dict[str, Any] = {
        "ext": ext,
        "file_size_bytes": size,
        "auto_route": auto_route,
    }

    if not auto_route:
        return TableRouteDecision(route="tag", reason="auto_route_disabled", stats=stats)

    fb = file_bytes_threshold
    if fb > 0 and size >= fb:
        stats.update({"trigger": "file_bytes", "file_bytes_threshold": fb})
        return TableRouteDecision(route="tag", reason="file_bytes_threshold", stats=stats)

    rt = row_threshold
    ct = col_threshold
    st = sheet_threshold

    if ext == ".csv":
        return _route_for_csv(
            file_path=file_path,
            stats=stats,
            row_threshold=rt,
            col_threshold=ct,
            csv_sample_bytes=csv_sample_bytes,
        )

    if ext == ".xlsx":
        return _route_for_xlsx(
            file_path=file_path,
            stats=stats,
            row_threshold=rt,
            col_threshold=ct,
            sheet_threshold=st,
        )

    # XLS (legacy): best-effort, file-size only (already applied).
    # We keep the default conservative: do not force TAG when we don't have signals.
    stats.update({"row_threshold": rt, "col_threshold": ct, "sheet_threshold": st, "shape_ok": False})
    return TableRouteDecision(route="rag", reason="legacy_xls_no_signal", stats=stats)


__all__ = ["Route", "TableRouteDecision", "decide_table_route"]
