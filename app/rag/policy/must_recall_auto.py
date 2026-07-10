
import re
from typing import Any

from app.rag.policy.must_recall import normalize_source_keys

_QUOTE_CHARS = "\"“”'‘’`"
_QUOTE_CLASS = re.escape(_QUOTE_CHARS)
_QUOTED_TERM_RE = re.compile(rf"[{_QUOTE_CLASS}]([^{_QUOTE_CLASS}]{{2,120}})[{_QUOTE_CLASS}]")
_FILE_LIKE_RE = re.compile(r"\b[A-Z0-9_.-]{2,120}\.(?:csv|tsv|xlsx|xls|md|txt|json)\b", re.IGNORECASE)
_TABLE_LIKE_RE = re.compile(r"\b[A-Za-z_]\w{1,80}\.[A-Za-z_]\w{1,80}\b")


def _collect_metadata_filter_source_keys(metadata_filter: Any) -> list[str]:
    if not isinstance(metadata_filter, dict):
        return []
    out: list[str] = []
    for key in ("table_id", "document_id", "document_name", "sheet_name", "source"):
        if key not in metadata_filter:
            continue
        raw = metadata_filter.get(key)
        if isinstance(raw, (list, tuple, set)):
            values = list(raw)
        else:
            values = [raw]
        for val in values:
            s = str(val or "").strip()
            if s:
                out.append(s)
    return out


def _collect_scope_source_keys(scope: Any) -> list[str]:
    if not isinstance(scope, dict):
        return []
    out: list[str] = []
    for key in ("source_keys", "table_ids", "document_ids"):
        if key not in scope:
            continue
        raw = scope.get(key)
        if isinstance(raw, (list, tuple, set)):
            values = list(raw)
        else:
            values = [raw]
        for val in values:
            s = str(val or "").strip()
            if s:
                out.append(s)
    return out


def infer_expected_source_keys(
    *,
    query: str,
    metadata_filter: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
    max_keys: int = 12,
) -> dict[str, Any]:
    q = str(query or "").strip()
    hints: list[str] = []
    reasons: list[str] = []

    if q:
        for m in _QUOTED_TERM_RE.finditer(q):
            s = str(m.group(1) or "").strip()
            if s:
                hints.append(s)
        if hints:
            reasons.append("query_quoted_terms")

        file_hits = [str(m.group(0) or "").strip() for m in _FILE_LIKE_RE.finditer(q)]
        if file_hits:
            hints.extend(file_hits)
            reasons.append("query_file_like")

        table_hits = [str(m.group(0) or "").strip() for m in _TABLE_LIKE_RE.finditer(q)]
        if table_hits:
            hints.extend(table_hits)
            reasons.append("query_table_like")

    meta_hits = _collect_metadata_filter_source_keys(metadata_filter)
    if meta_hits:
        hints.extend(meta_hits)
        reasons.append("metadata_filter")

    scope_hits = _collect_scope_source_keys(scope)
    if scope_hits:
        hints.extend(scope_hits)
        reasons.append("scope")

    normalized = normalize_source_keys(hints)
    normalized = normalized[: max(1, int(max_keys or 1))]
    confidence = "none"
    if normalized:
        confidence = "high" if len(reasons) >= 2 else "medium"

    return {
        "schema": "mimirq.must_recall_auto_source_keys.v1",
        "expected_source_keys": normalized,
        "reason_codes": list(reasons),
        "confidence": confidence,
    }


def infer_required_anchor_fields(
    *,
    query: str,
    default_fields: list[str] | tuple[str, ...] | None,
) -> dict[str, Any]:
    out = [str(v or "").strip().lower() for v in (default_fields or []) if str(v or "").strip()]
    reasons: list[str] = []
    q = str(query or "")
    q_fold = q.casefold()
    if any(k in q_fold for k in ("row", "rows", "哪一行", "行数据", "primary key", "主键")):
        for field in ("row_source_table", "row_source_pk_hashes", "row_source_sync_token"):
            if field not in out:
                out.append(field)
        reasons.append("row_level_intent")
    if any(k in q_fold for k in ("sheet", "worksheet", "表单", "工作表")) and "sheet_name" not in out:
        out.append("sheet_name")
        reasons.append("sheet_level_intent")
    out = normalize_source_keys(out)
    return {
        "schema": "mimirq.must_recall_auto_anchor_fields.v1",
        "required_anchor_fields": out,
        "reason_codes": list(reasons),
        "applied": bool(reasons),
    }


__all__ = [
    "infer_expected_source_keys",
    "infer_required_anchor_fields",
]
