"""
Chat <-> TAG bridge (Table Store).

This module allows the chat pipeline to answer table-like questions by:
  1) selecting likely relevant table assets (from doc_metadata.table_store),
  2) generating a bounded SELECT query (NL->SQL), and
  3) injecting the query result as additional context Documents.

Security / Safety
-----------------
- Only operates on documents already scoped by `document_ids` (ACL trimming happens upstream).
- Requires explicit feature flags:
  - CHAT_TAG_ENABLED=true
  - TABLE_NL2SQL_ENABLED=true (NL->SQL generation)
  - TABLE_LLM_ALLOW_RESULT_EGRESS=true (results will be sent to the LLM as context)
- Query execution remains SELECT-only with strict caps (run_table_query safeguards).
"""

import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid5

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.rag.policy.must_recall import normalize_source_keys
from app.services.table_sql_fingerprint import fingerprint_sql
from app.services.table_store_service import run_table_query
from app.services.table_tag_service import (
    generate_sql_for_table,
    generate_sql_for_table_with_metadata,
    plan_join_query_for_tables,
    score_schema_link_diagnostics,
)

_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}")
_TABLE_INTENT_RE = re.compile(
    r"(?i)\b(select|where|group\s+by|order\s+by|limit|sum|avg|count|min|max|distinct)\b"
    r"|统计|汇总|求和|平均|最大|最小|排名|Top\s*\d+|前\s*\d+|多少|几条|筛选|过滤|分组|占比"
)


@dataclass(frozen=True)
class _TableCandidate:
    document_id: UUID
    dataset_id: UUID
    filename: str
    file_type: str
    source_ext: str | None
    table_id: str
    sheet_index: int
    sheet_name: str | None
    row_count: int
    col_count: int
    columns: list[dict[str, Any]]
    sample_rows: list[dict[str, Any]]
    row_source_table: str | None
    row_source_sync_token: str | None
    row_source_pk_hash_col: str | None
    score: int


@dataclass(frozen=True)
class _TableQueryLimits:
    max_rows: int
    max_cols: int
    max_bytes: int


def _normalize_source_hint(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    s = s.strip("'\"`“”")
    return s


def _source_key_match(expected_key: str, candidate_value: str) -> bool:
    ek = _normalize_source_hint(expected_key)
    cv = _normalize_source_hint(candidate_value)
    if not ek or not cv:
        return False
    ek_fold = ek.casefold()
    cv_fold = cv.casefold()
    return bool(ek_fold == cv_fold or ek_fold in cv_fold or cv_fold in ek_fold)


def _candidate_source_keys(candidate: _TableCandidate) -> list[str]:
    out: list[str] = []
    for raw in (
        candidate.table_id,
        candidate.row_source_table,
        candidate.sheet_name,
        candidate.filename,
        str(candidate.document_id),
    ):
        s = _normalize_source_hint(str(raw or ""))
        if not s:
            continue
        if s not in out:
            out.append(s)
    filename = _normalize_source_hint(str(candidate.filename or ""))
    if filename and "." in filename:
        stem = filename.rsplit(".", 1)[0].strip()
        if stem and stem not in out:
            out.append(stem)
    return out


def _candidate_matches_source_keys(candidate: _TableCandidate, expected_source_keys: list[str]) -> bool:
    expected = [s for s in expected_source_keys if str(s or "").strip()]
    if not expected:
        return True
    values = _candidate_source_keys(candidate)
    if not values:
        return False
    for exp in expected:
        if any(_source_key_match(exp, val) for val in values):
            return True
    return False


def _enabled_reason() -> tuple[bool, str]:
    if not bool(getattr(settings, "CHAT_TAG_ENABLED", False)):
        return False, "CHAT_TAG_ENABLED=false"
    if not bool(getattr(settings, "TABLE_NL2SQL_ENABLED", False)):
        return False, "TABLE_NL2SQL_ENABLED=false"
    if not bool(getattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", False)):
        # Chat will inject query results into the LLM context; treat this as "result egress".
        return False, "TABLE_LLM_ALLOW_RESULT_EGRESS=false"
    has_llm_key = bool(str(getattr(settings, "LLM_API_KEY", "") or "").strip())
    deterministic_ok = bool(getattr(settings, "TABLE_NL2SQL_DETERMINISTIC_ONLY", False)) or bool(
        getattr(settings, "TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED", True)
    )
    if not has_llm_key and not deterministic_ok:
        return False, "LLM_API_KEY is not configured"
    return True, "ok"


def _extract_terms(text: str, *, max_terms: int = 12) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in _TERM_RE.finditer(raw):
        t = (m.group(0) or "").strip()
        if not t:
            continue
        key = t.casefold() if t.isascii() else t
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
        if len(out) >= max(1, int(max_terms or 0)):
            break
    return out


def _match_score(hay: str, term: str) -> bool:
    if not hay or not term:
        return False
    if term.isascii():
        return term.casefold() in hay.casefold()
    return term in hay


def _score_candidate(
    *,
    terms: list[str],
    filename: str,
    sheet_name: str | None,
    columns: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]],
) -> int:
    if not terms:
        return 0
    sample_blob = _sample_value_blob(sample_rows)
    col_names = [str(c.get("name") or "") for c in (columns or []) if isinstance(c, dict)]
    return sum(
        _score_candidate_term(
            term,
            filename=filename or "",
            sheet_name=sheet_name or "",
            col_names=col_names,
            sample_blob=sample_blob,
        )
        for term in terms
    )


def _sample_value_blob(sample_rows: list[dict[str, Any]]) -> str:
    sample_vals: list[str] = []
    for row in (sample_rows or [])[:12]:
        if not isinstance(row, dict):
            continue
        for value in list(row.values())[:40]:
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            sample_vals.append(text)
            if len(sample_vals) >= 400:
                return " ".join(sample_vals)[:8000]
    return " ".join(sample_vals)[:8000]


def _score_candidate_term(
    term: str,
    *,
    filename: str,
    sheet_name: str,
    col_names: list[str],
    sample_blob: str,
) -> int:
    if _match_score(filename, term):
        return 3
    if sheet_name and _match_score(sheet_name, term):
        return 4
    if any(_match_score(col_name, term) for col_name in col_names[:2000]):
        return 2
    if _sample_term_matches(sample_blob, term):
        return 1
    return 0


def _sample_term_matches(sample_blob: str, term: str) -> bool:
    if not sample_blob:
        return False
    if term.isascii() and len(term) < 4:
        return False
    return _match_score(sample_blob, term)


def _tag_doc_uuid(table_id: str) -> UUID:
    """
    Deterministic UUID for TAG-injected docs.

    Reason: chat API citations require UUID chunk_id; TAG context docs are not real chunks.
    """
    return uuid5(UUID("00000000-0000-0000-0000-000000000000"), f"mimirq:tag:{str(table_id or '').strip()}")


def build_chat_tag_context_docs(
    db: Session,
    *,
    tenant_id: UUID,
    document_ids: list[UUID],
    question: str,
    must_recall_expected_source_keys: list[str] | tuple[str, ...] | str | None = None,
) -> tuple[list[Document], dict[str, Any]]:
    """
    Build bounded context docs from Table Store assets for a chat question.

    Returns: (docs, meta)
    """
    enabled, reason = _enabled_reason()
    meta: dict[str, Any] = {"enabled": bool(enabled), "reason": reason, "used": False}
    if not enabled:
        return [], meta
    if db is None or tenant_id is None:
        meta["reason"] = "db_or_tenant_missing"
        return [], meta

    doc_ids = [doc_id for doc_id in (document_ids or []) if isinstance(doc_id, UUID)]
    if not doc_ids:
        meta["reason"] = "no_document_ids"
        return [], meta

    max_doc_ids = int(getattr(settings, "CHAT_TAG_MAX_DOC_IDS", 1000) or 1000)
    if max_doc_ids > 0 and len(doc_ids) > max_doc_ids:
        meta["reason"] = f"too_many_document_ids (max {max_doc_ids})"
        meta["document_ids"] = len(doc_ids)
        return [], meta

    intent = bool(_TABLE_INTENT_RE.search(question or ""))
    terms = _extract_terms(question or "", max_terms=12)
    candidates = _load_table_candidates(db, tenant_id=tenant_id, doc_ids=doc_ids, terms=terms)
    if not candidates:
        meta["reason"] = "no_table_assets"
        return [], meta

    candidates, expected_source_keys = _apply_source_key_match(
        candidates,
        must_recall_expected_source_keys=must_recall_expected_source_keys,
        meta=meta,
    )
    if not candidates:
        return [], meta

    picked = _pick_candidates(candidates, doc_ids=doc_ids, question=question, intent=intent, meta=meta)
    if not picked:
        return [], meta

    limits = _query_limits()
    multi_table_result = _try_multi_table_docs(
        tenant_id=tenant_id,
        question=question,
        candidates=candidates,
        picked=picked,
        intent=intent,
        expected_source_keys=expected_source_keys,
        meta=meta,
        limits=limits,
    )
    if multi_table_result is not None:
        return multi_table_result

    return _build_single_table_docs(
        tenant_id=tenant_id,
        question=question,
        candidates=candidates,
        picked=picked,
        intent=intent,
        expected_source_keys=expected_source_keys,
        meta=meta,
        limits=limits,
    )


def _load_table_candidates(
    db: Session,
    *,
    tenant_id: UUID,
    doc_ids: list[UUID],
    terms: list[str],
) -> list[_TableCandidate]:
    raw_docs = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.id.in_(doc_ids),
            DBDocument.status == "completed",
            DBDocument.file_type.in_(["csv", "xls", "xlsx", "docx", "pdf", "dbrows"]),
        )
        .all()
    )
    candidates: list[_TableCandidate] = []
    for document in raw_docs:
        candidates.extend(_table_candidates_from_document(document, terms=terms))
    return candidates


def _table_candidates_from_document(document: Any, *, terms: list[str]) -> list[_TableCandidate]:
    dataset_id = getattr(document, "dataset_id", None)
    if dataset_id is None:
        return []

    filename = str(getattr(document, "filename", "") or "").strip()
    file_type = str(getattr(document, "file_type", "") or "").strip().lower()
    metadata = getattr(document, "doc_metadata", None) or {}
    metadata = metadata if isinstance(metadata, dict) else {}
    store = metadata.get("table_store")
    if not isinstance(store, dict):
        return []

    source_ext = str(store.get("source_ext") or "").strip().lower() or None
    tables = store.get("tables")
    if not isinstance(tables, list):
        return []

    candidates: list[_TableCandidate] = []
    for table in tables:
        candidate = _table_candidate_from_store_entry(
            document=document,
            dataset_id=dataset_id,
            filename=filename,
            file_type=file_type,
            source_ext=source_ext,
            table=table,
            terms=terms,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _table_candidate_from_store_entry(
    *,
    document: Any,
    dataset_id: UUID,
    filename: str,
    file_type: str,
    source_ext: str | None,
    table: Any,
    terms: list[str],
) -> _TableCandidate | None:
    if not isinstance(table, dict):
        return None

    table_id = str(table.get("table_id") or "").strip()
    if not table_id:
        return None

    cols = table.get("columns")
    samples = table.get("sample_rows")
    columns = [col for col in cols if isinstance(col, dict)] if isinstance(cols, list) else []
    sample_rows = [row for row in samples if isinstance(row, dict)] if isinstance(samples, list) else []
    sheet_name = _optional_str(table.get("sheet_name"))
    return _TableCandidate(
        document_id=document.id,
        dataset_id=dataset_id,
        filename=filename,
        file_type=file_type,
        source_ext=source_ext,
        table_id=table_id,
        sheet_index=_safe_int(table.get("sheet_index")),
        sheet_name=sheet_name,
        row_count=_safe_int(table.get("row_count")),
        col_count=_safe_int(table.get("col_count")),
        columns=columns,
        sample_rows=sample_rows,
        row_source_table=_optional_str(table.get("row_source_table")),
        row_source_sync_token=_optional_str(table.get("row_source_sync_token")),
        row_source_pk_hash_col=_optional_str(table.get("row_source_pk_hash_col")),
        score=_score_candidate(
            terms=terms,
            filename=filename,
            sheet_name=sheet_name,
            columns=columns,
            sample_rows=sample_rows,
        ),
    )


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _optional_str(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _apply_source_key_match(
    candidates: list[_TableCandidate],
    *,
    must_recall_expected_source_keys: list[str] | tuple[str, ...] | str | None,
    meta: dict[str, Any],
) -> tuple[list[_TableCandidate], list[str]]:
    expected_source_keys = normalize_source_keys(must_recall_expected_source_keys)
    source_key_match_enabled = bool(getattr(settings, "CHAT_TAG_MUST_RECALL_SOURCE_KEY_MATCH", True))
    meta["must_recall_source_key_match_enabled"] = bool(source_key_match_enabled)
    if expected_source_keys:
        meta["must_recall_expected_source_keys"] = expected_source_keys[:20]
    if not source_key_match_enabled or not expected_source_keys:
        return candidates, expected_source_keys

    pre_filter_count = len(candidates)
    filtered = [
        candidate for candidate in candidates if _candidate_matches_source_keys(candidate, expected_source_keys)
    ]
    meta["must_recall_source_key_match_applied"] = True
    meta["must_recall_source_key_match_candidates_before"] = int(pre_filter_count)
    meta["must_recall_source_key_match_candidates_after"] = int(len(filtered))
    if filtered:
        return filtered, expected_source_keys

    meta["reason"] = "must_recall_source_key_miss"
    return [], expected_source_keys


def _pick_candidates(
    candidates: list[_TableCandidate],
    *,
    doc_ids: list[UUID],
    question: str,
    intent: bool,
    meta: dict[str, Any],
) -> list[_TableCandidate]:
    min_score = int(getattr(settings, "CHAT_TAG_MIN_MATCH_SCORE", 1) or 1)
    best_score = max((candidate.score for candidate in candidates), default=0)
    if not _passes_match_threshold(candidates, doc_ids=doc_ids, best_score=best_score, intent=intent, meta=meta):
        return []

    complex_query = bool(
        re.search(r"(?i)\b(join|group\s+by|by|per|across|between)\b|按|分组|关联|维度|同比|环比", str(question or ""))
    )
    effective_max_tables, table_pick_policy = _table_pick_policy(
        candidates,
        min_score=min_score,
        intent=intent,
        complex_query=complex_query,
    )
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            -int(candidate.score),
            -int(candidate.row_count),
            str(candidate.filename),
            str(candidate.table_id),
        ),
    )
    picked = ordered[:effective_max_tables] if effective_max_tables > 0 else []
    if not picked:
        meta["reason"] = "no_candidates_picked"
        return []

    meta["table_pick_policy"] = table_pick_policy
    meta["effective_max_tables"] = int(effective_max_tables)
    return picked


def _passes_match_threshold(
    candidates: list[_TableCandidate],
    *,
    doc_ids: list[UUID],
    best_score: int,
    intent: bool,
    meta: dict[str, Any],
) -> bool:
    min_score = int(getattr(settings, "CHAT_TAG_MIN_MATCH_SCORE", 1) or 1)
    if not intent and best_score < min_score:
        meta["reason"] = "no_intent_and_no_match"
        meta["best_score"] = int(best_score)
        return False
    if not intent or best_score >= min_score:
        return True
    return _intent_match_fallback(candidates, doc_ids=doc_ids, best_score=best_score, meta=meta)


def _intent_match_fallback(
    candidates: list[_TableCandidate],
    *,
    doc_ids: list[UUID],
    best_score: int,
    meta: dict[str, Any],
) -> bool:
    unique_doc_ids = {candidate.document_id for candidate in candidates}
    if len(doc_ids) == 1 or len(candidates) == 1 or (len(unique_doc_ids) == 1 and len(doc_ids) == 1):
        meta["selection_fallback"] = "single_document" if len(doc_ids) == 1 else "single_table"
        return True
    meta["reason"] = "intent_no_match_ambiguous"
    meta["best_score"] = int(best_score)
    meta["candidates"] = int(len(candidates))
    meta["documents_with_tables"] = int(len(unique_doc_ids))
    return False


def _table_pick_policy(
    candidates: list[_TableCandidate],
    *,
    min_score: int,
    intent: bool,
    complex_query: bool,
) -> tuple[int, str]:
    max_tables = int(getattr(settings, "CHAT_TAG_MAX_TABLES", 2) or 2)
    max_tables = max(0, min(max_tables, 5))
    high_conf = [candidate for candidate in candidates if int(candidate.score) >= int(min_score)]
    if max_tables > 1 and complex_query and len(candidates) >= 2 and intent:
        return min(max_tables, 2), "complexity_schema_link_multi_table"
    if not intent or len(high_conf) <= 1:
        return min(max_tables, 1), "single_table_low_complexity"
    return int(max_tables), "default_cap"


def _query_limits() -> _TableQueryLimits:
    max_rows = int(getattr(settings, "CHAT_TAG_MAX_ROWS", 50) or 50)
    max_cols = int(getattr(settings, "CHAT_TAG_MAX_COLS", 30) or 30)
    max_bytes = int(getattr(settings, "CHAT_TAG_MAX_BYTES", 200_000) or 200_000)
    if max_rows <= 0:
        max_rows = 50
    if max_cols <= 0:
        max_cols = 30
    if max_bytes <= 10_000:
        max_bytes = 10_000
    return _TableQueryLimits(max_rows=max_rows, max_cols=max_cols, max_bytes=max_bytes)


def _try_multi_table_docs(
    *,
    tenant_id: UUID,
    question: str,
    candidates: list[_TableCandidate],
    picked: list[_TableCandidate],
    intent: bool,
    expected_source_keys: list[str],
    meta: dict[str, Any],
    limits: _TableQueryLimits,
) -> tuple[list[Document], dict[str, Any]] | None:
    if not _supports_multi_table_path(picked):
        return None
    try:
        return _build_multi_table_docs(
            tenant_id=tenant_id,
            question=question,
            candidates=candidates,
            picked=picked,
            intent=intent,
            expected_source_keys=expected_source_keys,
            meta=meta,
            limits=limits,
        )
    except Exception as exc:  # noqa: BLE001
        meta["multi_table_error"] = str(exc)[:200]
        return None


def _supports_multi_table_path(picked: list[_TableCandidate]) -> bool:
    if len(picked) < 2:
        return False
    same_document = len({candidate.document_id for candidate in picked}) == 1
    same_dataset = len({candidate.dataset_id for candidate in picked}) == 1
    return same_document and same_dataset


def _build_multi_table_docs(
    *,
    tenant_id: UUID,
    question: str,
    candidates: list[_TableCandidate],
    picked: list[_TableCandidate],
    intent: bool,
    expected_source_keys: list[str],
    meta: dict[str, Any],
    limits: _TableQueryLimits,
) -> tuple[list[Document], dict[str, Any]]:
    join_inputs, by_sql_table = _join_inputs_for_candidates(picked)
    join_plan = plan_join_query_for_tables(question=str(question or ""), tables=join_inputs, max_rows=limits.max_rows)
    join_sql = str(join_plan.get("sql") or "").strip()
    planner_diagnostics = _planner_dict(join_plan.get("planner") if isinstance(join_plan, dict) else None)
    join_provenance = planner_diagnostics.get("joins")
    if not isinstance(join_provenance, list):
        join_provenance = []
    join_plan_risk = _join_plan_risk(planner_diagnostics)
    sql_fingerprint = _sql_fingerprint_from_planner(planner_diagnostics, join_sql)
    selected_sql_tables = _selected_sql_tables(planner_diagnostics, by_sql_table)
    selected_candidates = _selected_join_candidates(selected_sql_tables, by_sql_table, picked)
    primary = selected_candidates[0]
    schema_link_diagnostics = _merged_join_schema_link(question=question, selected_candidates=selected_candidates)
    result = run_table_query(
        tenant_id=tenant_id,
        dataset_id=primary.dataset_id,
        table_id=primary.table_id,
        sql=join_sql,
        max_rows=limits.max_rows,
        max_cols=limits.max_cols,
        max_bytes=limits.max_bytes,
        allowed_sql_tables=selected_sql_tables,
        planner_diagnostics=planner_diagnostics,
        expected_sql_fingerprint=sql_fingerprint,
    )
    planner_execution_mismatch = _planner_execution_mismatch(result)
    _raise_for_strict_planner_mismatch(planner_execution_mismatch)
    source_key_match = _candidate_matches_source_keys(primary, expected_source_keys)
    payload = _build_multi_table_payload(
        primary=primary,
        join_sql=join_sql,
        result=result,
        sql_fingerprint=sql_fingerprint,
        schema_link_diagnostics=schema_link_diagnostics,
        planner_diagnostics=planner_diagnostics,
        join_plan_risk=join_plan_risk,
        planner_execution_mismatch=planner_execution_mismatch,
        join_provenance=join_provenance,
        selected_candidates=selected_candidates,
        selected_sql_tables=selected_sql_tables,
        source_key_match=source_key_match,
        expected_source_keys=expected_source_keys,
    )
    document = _multi_table_document(
        primary=primary,
        payload=payload,
        sql_fingerprint=sql_fingerprint,
        schema_link_diagnostics=schema_link_diagnostics,
        planner_diagnostics=planner_diagnostics,
        join_plan_risk=join_plan_risk,
        planner_execution_mismatch=planner_execution_mismatch,
        join_provenance=join_provenance,
        selected_candidates=selected_candidates,
        selected_sql_tables=selected_sql_tables,
        source_key_match=source_key_match,
        expected_source_keys=expected_source_keys,
    )
    meta.update(
        {
            "used": True,
            "intent": bool(intent),
            "candidates": int(len(candidates)),
            "picked": int(len(selected_candidates)),
            "returned": 1,
            "multi_table": True,
            "errors": [],
        }
    )
    return [document], meta


def _join_inputs_for_candidates(
    picked: list[_TableCandidate],
) -> tuple[list[dict[str, Any]], dict[str, _TableCandidate]]:
    join_inputs: list[dict[str, Any]] = []
    by_sql_table: dict[str, _TableCandidate] = {}
    for candidate in picked:
        sql_table = f"sheet_{int(candidate.sheet_index)}"
        by_sql_table[sql_table] = candidate
        join_inputs.append(
            {
                "table_name": sql_table,
                "table_aliases": [candidate.table_id, candidate.filename, str(candidate.sheet_name or "")],
                "columns": candidate.columns,
                "row_count": int(candidate.row_count),
                "sample_rows": candidate.sample_rows,
            }
        )
    return join_inputs, by_sql_table


def _planner_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _join_plan_risk(planner_diagnostics: dict[str, Any]) -> dict[str, Any] | None:
    risk = planner_diagnostics.get("join_plan_risk")
    return risk if isinstance(risk, dict) else None


def _sql_fingerprint_from_planner(planner_diagnostics: dict[str, Any], sql: str) -> str:
    return str(planner_diagnostics.get("sql_fingerprint") or "").strip() or fingerprint_sql(sql, length=16)


def _selected_sql_tables(
    planner_diagnostics: dict[str, Any],
    by_sql_table: dict[str, _TableCandidate],
) -> list[str]:
    selected = [
        str(value).strip() for value in (planner_diagnostics.get("selected_tables") or []) if str(value).strip()
    ]
    return selected or list(by_sql_table.keys())[:2]


def _selected_join_candidates(
    selected_sql_tables: list[str],
    by_sql_table: dict[str, _TableCandidate],
    picked: list[_TableCandidate],
) -> list[_TableCandidate]:
    selected = [by_sql_table[table] for table in selected_sql_tables if table in by_sql_table]
    return selected or list(picked[:2])


def _merged_join_schema_link(
    *,
    question: str,
    selected_candidates: list[_TableCandidate],
) -> dict[str, Any]:
    matched_columns: list[str] = []
    matched_values: list[str] = []
    matched_tables: list[str] = []
    score_values: list[float] = []
    for candidate in selected_candidates:
        diagnostics = score_schema_link_diagnostics(
            question=str(question or ""),
            sql_table=f"sheet_{int(candidate.sheet_index)}",
            columns=candidate.columns,
            sample_rows=candidate.sample_rows,
            table_aliases=[candidate.table_id, candidate.filename, str(candidate.sheet_name or "")],
        )
        _extend_unique_strings(matched_columns, diagnostics.get("matched_columns"))
        _extend_unique_strings(matched_values, diagnostics.get("matched_values"))
        _extend_unique_strings(matched_tables, diagnostics.get("matched_tables"))
        score_values.append(_safe_float(diagnostics.get("score")))
    return {
        "score": round(max(score_values) if score_values else 0.0, 3),
        "strategy": "multi_table_join",
        "reason": "joined_table_schema_overlap",
        "matched_columns": matched_columns[:20],
        "matched_values": matched_values[:20],
        "matched_tables": matched_tables[:20],
    }


def _extend_unique_strings(values: list[str], raw_values: Any) -> None:
    if not isinstance(raw_values, list):
        return
    for raw in raw_values:
        text = str(raw or "").strip()
        if text and text not in values:
            values.append(text)


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _planner_execution_mismatch(result: dict[str, Any]) -> dict[str, Any] | None:
    mismatch = result.get("planner_execution_mismatch")
    return mismatch if isinstance(mismatch, dict) else None


def _raise_for_strict_planner_mismatch(planner_execution_mismatch: dict[str, Any] | None) -> None:
    mismatch_strict = bool(getattr(settings, "TABLE_TAG_PLANNER_MISMATCH_STRICT", False))
    if mismatch_strict and planner_execution_mismatch and bool(planner_execution_mismatch.get("mismatch")):
        raise ValueError("planner_execution_mismatch")


def _build_multi_table_payload(
    *,
    primary: _TableCandidate,
    join_sql: str,
    result: dict[str, Any],
    sql_fingerprint: str,
    schema_link_diagnostics: dict[str, Any],
    planner_diagnostics: dict[str, Any],
    join_plan_risk: dict[str, Any] | None,
    planner_execution_mismatch: dict[str, Any] | None,
    join_provenance: list[Any],
    selected_candidates: list[_TableCandidate],
    selected_sql_tables: list[str],
    source_key_match: bool,
    expected_source_keys: list[str],
) -> dict[str, Any]:
    payload = {
        "kind": "tag_table_store",
        "document": primary.filename,
        "table_id": primary.table_id,
        "sheet_index": int(primary.sheet_index),
        "sheet_name": primary.sheet_name,
        "row_count": int(primary.row_count),
        "col_count": int(primary.col_count),
        "sql": str(result.get("sql") or join_sql),
        "sql_fingerprint": sql_fingerprint,
        "sql_generation_mode": "deterministic_join",
        "schema_link": schema_link_diagnostics,
        "planner": planner_diagnostics,
        "join_plan_risk": join_plan_risk,
        "planner_execution_mismatch": planner_execution_mismatch,
        "join_provenance": join_provenance,
        "join_table_ids": [candidate.table_id for candidate in selected_candidates],
        "join_sql_tables": selected_sql_tables,
        "must_recall_source_key_match": bool(source_key_match),
        "must_recall_expected_source_keys": expected_source_keys[:20],
        "columns": result.get("columns") if isinstance(result.get("columns"), list) else [],
        "rows": result.get("rows") if isinstance(result.get("rows"), list) else [],
        "truncated": bool(result.get("truncated")),
    }
    return _bounded_payload_text(payload)[1]


def _multi_table_document(
    *,
    primary: _TableCandidate,
    payload: dict[str, Any],
    sql_fingerprint: str,
    schema_link_diagnostics: dict[str, Any],
    planner_diagnostics: dict[str, Any],
    join_plan_risk: dict[str, Any] | None,
    planner_execution_mismatch: dict[str, Any] | None,
    join_provenance: list[Any],
    selected_candidates: list[_TableCandidate],
    selected_sql_tables: list[str],
    source_key_match: bool,
    expected_source_keys: list[str],
) -> Document:
    text, _payload = _bounded_payload_text(payload)
    return Document(
        page_content=text,
        metadata={
            "document_id": primary.document_id,
            "source": primary.filename or "table",
            "retrieval_role": "tag",
            "chunk_strategy": "tag",
            "chunk_role": "tag_sql_result",
            "table_id": primary.table_id,
            "sheet_index": int(primary.sheet_index),
            "sheet_name": primary.sheet_name,
            "sql_fingerprint": sql_fingerprint,
            "sql_generation_mode": "deterministic_join",
            "schema_link_score": schema_link_diagnostics.get("score"),
            "schema_link_strategy": schema_link_diagnostics.get("strategy"),
            "schema_link_reason": schema_link_diagnostics.get("reason"),
            "schema_link_diagnostics": schema_link_diagnostics,
            "planner_diagnostics": planner_diagnostics,
            "join_plan_risk": join_plan_risk,
            "join_plan_risk_fanout_explosive": bool((join_plan_risk or {}).get("fanout_explosive")),
            "join_plan_risk_selectivity_unknown": bool((join_plan_risk or {}).get("selectivity_unknown")),
            "planner_execution_mismatch": planner_execution_mismatch,
            "join_provenance": join_provenance,
            "join_table_ids": [candidate.table_id for candidate in selected_candidates],
            "join_sql_tables": selected_sql_tables,
            "must_recall_source_key_match": bool(source_key_match),
            "must_recall_expected_source_keys": expected_source_keys[:20],
            "score": 1.0,
            "retrieval_score": 1.0,
        },
        id=str(_tag_doc_uuid(primary.table_id)),
    )


def _build_single_table_docs(
    *,
    tenant_id: UUID,
    question: str,
    candidates: list[_TableCandidate],
    picked: list[_TableCandidate],
    intent: bool,
    expected_source_keys: list[str],
    meta: dict[str, Any],
    limits: _TableQueryLimits,
) -> tuple[list[Document], dict[str, Any]]:
    out_docs: list[Document] = []
    errors: list[str] = []
    for candidate in picked:
        try:
            out_docs.append(
                _single_table_document(
                    tenant_id=tenant_id,
                    question=question,
                    candidate=candidate,
                    expected_source_keys=expected_source_keys,
                    limits=limits,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{candidate.table_id}:{str(exc)[:160]}")
    meta.update(
        {
            "used": bool(out_docs),
            "intent": bool(intent),
            "candidates": int(len(candidates)),
            "picked": int(len(picked)),
            "returned": int(len(out_docs)),
            "errors": errors[:5],
        }
    )
    return out_docs, meta


def _single_table_document(
    *,
    tenant_id: UUID,
    question: str,
    candidate: _TableCandidate,
    expected_source_keys: list[str],
    limits: _TableQueryLimits,
) -> Document:
    sql_table = f"sheet_{int(candidate.sheet_index)}"
    schema_link_diagnostics = score_schema_link_diagnostics(
        question=str(question or ""),
        sql_table=sql_table,
        columns=candidate.columns,
        sample_rows=candidate.sample_rows,
        table_aliases=[candidate.table_id, candidate.filename, str(candidate.sheet_name or "")],
    )
    sql, sql_generation_mode, sql_fingerprint, planner_diagnostics, schema_link_diagnostics = _single_table_sql_plan(
        candidate=candidate,
        question=question,
        sql_table=sql_table,
        limits=limits,
        schema_link_diagnostics=schema_link_diagnostics,
    )
    join_plan_risk = _join_plan_risk(planner_diagnostics) if isinstance(planner_diagnostics, dict) else None
    result = run_table_query(
        tenant_id=tenant_id,
        dataset_id=candidate.dataset_id,
        table_id=candidate.table_id,
        sql=sql,
        max_rows=limits.max_rows,
        max_cols=limits.max_cols,
        max_bytes=limits.max_bytes,
        planner_diagnostics=planner_diagnostics,
        expected_sql_fingerprint=sql_fingerprint,
    )
    planner_execution_mismatch = _planner_execution_mismatch(result)
    _raise_for_strict_planner_mismatch(planner_execution_mismatch)
    source_key_match = _candidate_matches_source_keys(candidate, expected_source_keys)
    payload = _single_table_payload(
        candidate=candidate,
        sql=sql,
        result=result,
        sql_fingerprint=sql_fingerprint,
        sql_generation_mode=sql_generation_mode,
        schema_link_diagnostics=schema_link_diagnostics,
        planner_diagnostics=planner_diagnostics,
        join_plan_risk=join_plan_risk,
        planner_execution_mismatch=planner_execution_mismatch,
        source_key_match=source_key_match,
        expected_source_keys=expected_source_keys,
    )
    return _single_table_payload_document(
        candidate=candidate,
        payload=payload,
        sql_fingerprint=sql_fingerprint,
        sql_generation_mode=sql_generation_mode,
        schema_link_diagnostics=schema_link_diagnostics,
        planner_diagnostics=planner_diagnostics,
        join_plan_risk=join_plan_risk,
        planner_execution_mismatch=planner_execution_mismatch,
        source_key_match=source_key_match,
        expected_source_keys=expected_source_keys,
    )


def _single_table_sql_plan(
    *,
    candidate: _TableCandidate,
    question: str,
    sql_table: str,
    limits: _TableQueryLimits,
    schema_link_diagnostics: dict[str, Any],
) -> tuple[str, str, str, dict[str, Any] | None, dict[str, Any]]:
    planner_diagnostics: dict[str, Any] | None = None
    sql_generation_mode = "llm"
    sql_fingerprint = ""
    has_llm_key = bool(str(getattr(settings, "LLM_API_KEY", "") or "").strip())
    deterministic_only = bool(getattr(settings, "TABLE_NL2SQL_DETERMINISTIC_ONLY", False))
    deterministic_fallback = bool(getattr(settings, "TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED", True))
    dbrows_sql_first = bool(
        getattr(settings, "CHAT_TAG_DBROWS_SQL_FIRST_ENABLED", True) and _is_dbrows_candidate(candidate)
    )

    if deterministic_only or dbrows_sql_first or (not has_llm_key and deterministic_fallback):
        sql, sql_generation_mode, sql_meta = generate_sql_for_table_with_metadata(
            question=str(question or ""),
            sql_table=sql_table,
            columns=candidate.columns,
            max_rows=limits.max_rows,
            sample_rows=candidate.sample_rows,
            table_aliases=[candidate.table_id, candidate.filename, str(candidate.sheet_name or "")],
        )
        planner_diagnostics, schema_link_diagnostics, sql_fingerprint = _sql_plan_metadata(
            sql_meta,
            schema_link_diagnostics=schema_link_diagnostics,
        )
    else:
        sql = generate_sql_for_table(
            question=str(question or ""),
            sql_table=sql_table,
            columns=candidate.columns,
            max_rows=limits.max_rows,
        )
        planner_diagnostics = {"strategy": "llm", "reason": "llm_generation"}

    if not sql_fingerprint:
        sql_fingerprint = fingerprint_sql(sql, length=16)
    if isinstance(planner_diagnostics, dict):
        planner_diagnostics = dict(planner_diagnostics)
        planner_diagnostics.setdefault("sql_fingerprint", sql_fingerprint)
    return sql, sql_generation_mode, sql_fingerprint, planner_diagnostics, schema_link_diagnostics


def _is_dbrows_candidate(candidate: _TableCandidate) -> bool:
    return bool(
        str(candidate.file_type or "").strip().lower() == "dbrows"
        or str(candidate.source_ext or "").strip().lower() == ".dbrows"
        or str(candidate.filename or "").strip().lower().endswith(".dbrows")
    )


def _sql_plan_metadata(
    sql_meta: Any,
    *,
    schema_link_diagnostics: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any], str]:
    if not isinstance(sql_meta, dict):
        return None, schema_link_diagnostics, ""
    linked = sql_meta.get("schema_link")
    if isinstance(linked, dict):
        schema_link_diagnostics = linked
    planner = sql_meta.get("planner")
    planner_diagnostics = planner if isinstance(planner, dict) else None
    planner_fp = ""
    if isinstance(planner_diagnostics, dict):
        planner_fp = str(planner_diagnostics.get("sql_fingerprint") or "").strip()
    sql_fingerprint = str(sql_meta.get("sql_fingerprint") or planner_fp or "").strip()
    return planner_diagnostics, schema_link_diagnostics, sql_fingerprint


def _single_table_payload(
    *,
    candidate: _TableCandidate,
    sql: str,
    result: dict[str, Any],
    sql_fingerprint: str,
    sql_generation_mode: str,
    schema_link_diagnostics: dict[str, Any],
    planner_diagnostics: dict[str, Any] | None,
    join_plan_risk: dict[str, Any] | None,
    planner_execution_mismatch: dict[str, Any] | None,
    source_key_match: bool,
    expected_source_keys: list[str],
) -> dict[str, Any]:
    payload = {
        "kind": "tag_table_store",
        "document": candidate.filename,
        "table_id": candidate.table_id,
        "sheet_index": int(candidate.sheet_index),
        "sheet_name": candidate.sheet_name,
        "row_count": int(candidate.row_count),
        "col_count": int(candidate.col_count),
        "sql": str(result.get("sql") or sql),
        "sql_fingerprint": sql_fingerprint,
        "sql_generation_mode": sql_generation_mode,
        "schema_link": schema_link_diagnostics,
        "planner": planner_diagnostics,
        "join_plan_risk": join_plan_risk,
        "planner_execution_mismatch": planner_execution_mismatch,
        "must_recall_source_key_match": bool(source_key_match),
        "must_recall_expected_source_keys": expected_source_keys[:20],
        "columns": result.get("columns") if isinstance(result.get("columns"), list) else [],
        "rows": result.get("rows") if isinstance(result.get("rows"), list) else [],
        "truncated": bool(result.get("truncated")),
    }
    row_source = _row_source_payload(candidate, payload)
    if row_source:
        payload["row_source"] = row_source
    return payload


def _row_source_payload(candidate: _TableCandidate, payload: dict[str, Any]) -> dict[str, Any]:
    if not (candidate.row_source_table or candidate.row_source_sync_token or candidate.row_source_pk_hash_col):
        return {}

    row_source: dict[str, Any] = {}
    if candidate.row_source_table:
        row_source["table"] = candidate.row_source_table
    if candidate.row_source_sync_token:
        row_source["sync_token"] = candidate.row_source_sync_token
    pk_hashes = _row_source_pk_hashes(candidate, payload)
    if pk_hashes:
        row_source["pk_hashes"] = pk_hashes
    return row_source


def _row_source_pk_hashes(candidate: _TableCandidate, payload: dict[str, Any]) -> list[str]:
    pk_hash_col = str(candidate.row_source_pk_hash_col or "__row_pk_hash").strip() or "__row_pk_hash"
    column_names = payload.get("columns") if isinstance(payload.get("columns"), list) else []
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    if pk_hash_col not in column_names or not rows:
        return []
    idx_pk = column_names.index(pk_hash_col)
    pk_hashes: list[str] = []
    for row in rows:
        if not isinstance(row, list) or idx_pk >= len(row):
            continue
        value = str(row[idx_pk] or "").strip()
        if not value or value in pk_hashes:
            continue
        pk_hashes.append(value)
        if len(pk_hashes) >= 200:
            break
    return pk_hashes


def _single_table_payload_document(
    *,
    candidate: _TableCandidate,
    payload: dict[str, Any],
    sql_fingerprint: str,
    sql_generation_mode: str,
    schema_link_diagnostics: dict[str, Any],
    planner_diagnostics: dict[str, Any] | None,
    join_plan_risk: dict[str, Any] | None,
    planner_execution_mismatch: dict[str, Any] | None,
    source_key_match: bool,
    expected_source_keys: list[str],
) -> Document:
    text, bounded_payload = _bounded_payload_text(payload)
    row_source = bounded_payload.get("row_source")
    return Document(
        page_content=text,
        metadata={
            "document_id": candidate.document_id,
            "source": candidate.filename or "table",
            "retrieval_role": "tag",
            "chunk_strategy": "tag",
            "chunk_role": "tag_sql_result",
            "table_id": candidate.table_id,
            "sheet_index": int(candidate.sheet_index),
            "sheet_name": candidate.sheet_name,
            "sql_fingerprint": sql_fingerprint,
            "sql_generation_mode": sql_generation_mode,
            "schema_link_score": (
                schema_link_diagnostics.get("score") if isinstance(schema_link_diagnostics, dict) else None
            ),
            "schema_link_strategy": (
                schema_link_diagnostics.get("strategy") if isinstance(schema_link_diagnostics, dict) else None
            ),
            "schema_link_reason": (
                schema_link_diagnostics.get("reason") if isinstance(schema_link_diagnostics, dict) else None
            ),
            "schema_link_diagnostics": schema_link_diagnostics,
            "planner_diagnostics": planner_diagnostics,
            "join_plan_risk": join_plan_risk,
            "join_plan_risk_fanout_explosive": bool((join_plan_risk or {}).get("fanout_explosive")),
            "join_plan_risk_selectivity_unknown": bool((join_plan_risk or {}).get("selectivity_unknown")),
            "planner_execution_mismatch": planner_execution_mismatch,
            "must_recall_source_key_match": bool(source_key_match),
            "must_recall_expected_source_keys": expected_source_keys[:20],
            "row_source_table": row_source.get("table") if isinstance(row_source, dict) else candidate.row_source_table,
            "row_source_sync_token": (
                row_source.get("sync_token") if isinstance(row_source, dict) else candidate.row_source_sync_token
            ),
            "row_source_pk_hashes": row_source.get("pk_hashes") if isinstance(row_source, dict) else None,
            "score": 1.0,
            "retrieval_score": 1.0,
        },
        id=str(_tag_doc_uuid(candidate.table_id)),
    )


def _bounded_payload_text(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    bounded_payload = dict(payload)
    text = json.dumps(bounded_payload, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= 12_000:
        return text, bounded_payload
    bounded_payload["rows"] = bounded_payload.get("rows", [])[:10]
    text = json.dumps(bounded_payload, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= 12_000:
        return text, bounded_payload
    return text[:12_000] + "...", bounded_payload


__all__ = ["build_chat_tag_context_docs"]
