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
    return bool(
        ek_fold == cv_fold
        or ek_fold in cv_fold
        or cv_fold in ek_fold
    )


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
    score = 0
    fn = filename or ""
    sn = sheet_name or ""
    col_names = [str(c.get("name") or "") for c in (columns or []) if isinstance(c, dict)]

    # Small bounded blob of values seen in metadata sample rows.
    # This improves table selection when users mention values (IDs/names) rather than column names.
    sample_vals: list[str] = []
    for row in (sample_rows or [])[:12]:
        if not isinstance(row, dict):
            continue
        for v in list(row.values())[:40]:
            if v is None:
                continue
            s = str(v).strip()
            if not s:
                continue
            sample_vals.append(s)
            if len(sample_vals) >= 400:
                break
        if len(sample_vals) >= 400:
            break
    sample_blob = " ".join(sample_vals)[:8000]

    for t in terms:
        if _match_score(fn, t):
            score += 3
            continue
        if sn and _match_score(sn, t):
            score += 4
            continue
        if any(_match_score(cn, t) for cn in col_names[:2000]):
            score += 2
            continue
        # Sample value match is intentionally weaker and only for "informative" terms
        # (avoid matching short, common tokens like "no"/"ok").
        if sample_blob:
            if t.isascii() and len(t) < 4:
                continue
            if _match_score(sample_blob, t):
                score += 1
    return int(score)


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

    doc_ids = [d for d in (document_ids or []) if isinstance(d, UUID)]
    if not doc_ids:
        meta["reason"] = "no_document_ids"
        return [], meta

    max_doc_ids = int(getattr(settings, "CHAT_TAG_MAX_DOC_IDS", 1000) or 1000)
    if max_doc_ids > 0 and len(doc_ids) > max_doc_ids:
        meta["reason"] = f"too_many_document_ids (max {max_doc_ids})"
        meta["document_ids"] = len(doc_ids)
        return [], meta

    # Quick intent check: avoid unnecessary NL->SQL calls for narrative Q&A.
    intent = bool(_TABLE_INTENT_RE.search(question or ""))
    terms = _extract_terms(question or "", max_terms=12)

    # Load table-like docs (already ACL-trimmed by upstream document_ids).
    q = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.id.in_(doc_ids),
            DBDocument.status == "completed",
            # DOCX can have embedded tables imported into the Table Store as a sidecar.
            # PDF can also emit parsed tables that we store in the Table Store (sidecar).
            DBDocument.file_type.in_(["csv", "xls", "xlsx", "docx", "pdf", "dbrows"]),
        )
    )
    raw_docs = q.all()
    if not raw_docs:
        meta["reason"] = "no_table_documents"
        return [], meta

    candidates: list[_TableCandidate] = []
    for d in raw_docs:
        dataset_id = getattr(d, "dataset_id", None)
        if dataset_id is None:
            continue
        filename = str(getattr(d, "filename", "") or "").strip()
        file_type = str(getattr(d, "file_type", "") or "").strip().lower()
        md = getattr(d, "doc_metadata", None) or {}
        md = md if isinstance(md, dict) else {}
        store = md.get("table_store")
        if not isinstance(store, dict):
            continue
        source_ext = str(store.get("source_ext") or "").strip().lower() or None
        tables = store.get("tables")
        if not isinstance(tables, list):
            continue
        for t in tables:
            if not isinstance(t, dict):
                continue
            table_id = str(t.get("table_id") or "").strip()
            if not table_id:
                continue
            try:
                sheet_index = int(t.get("sheet_index") or 0)
            except Exception:
                sheet_index = 0
            sheet_name = t.get("sheet_name")
            sheet_name = str(sheet_name) if sheet_name is not None else None
            try:
                row_count = int(t.get("row_count") or 0)
            except Exception:
                row_count = 0
            try:
                col_count = int(t.get("col_count") or 0)
            except Exception:
                col_count = 0
            cols = t.get("columns")
            cols_list = [c for c in cols if isinstance(c, dict)] if isinstance(cols, list) else []
            samples = t.get("sample_rows")
            samples_list = [r for r in samples if isinstance(r, dict)] if isinstance(samples, list) else []
            row_source_table = str(t.get("row_source_table") or "").strip() or None
            row_source_sync_token = str(t.get("row_source_sync_token") or "").strip() or None
            row_source_pk_hash_col = str(t.get("row_source_pk_hash_col") or "").strip() or None

            score = _score_candidate(
                terms=terms,
                filename=filename,
                sheet_name=sheet_name,
                columns=cols_list,
                sample_rows=samples_list,
            )
            candidates.append(
                _TableCandidate(
                    document_id=d.id,
                    dataset_id=dataset_id,
                    filename=filename,
                    file_type=file_type,
                    source_ext=source_ext,
                    table_id=table_id,
                    sheet_index=sheet_index,
                    sheet_name=sheet_name,
                    row_count=row_count,
                    col_count=col_count,
                    columns=cols_list,
                    sample_rows=samples_list,
                    row_source_table=row_source_table,
                    row_source_sync_token=row_source_sync_token,
                    row_source_pk_hash_col=row_source_pk_hash_col,
                    score=score,
                )
            )

    if not candidates:
        meta["reason"] = "no_table_assets"
        return [], meta

    expected_source_keys = normalize_source_keys(must_recall_expected_source_keys)
    source_key_match_enabled = bool(getattr(settings, "CHAT_TAG_MUST_RECALL_SOURCE_KEY_MATCH", True))
    source_key_match_applied = bool(source_key_match_enabled and expected_source_keys)
    meta["must_recall_source_key_match_enabled"] = bool(source_key_match_enabled)
    if expected_source_keys:
        meta["must_recall_expected_source_keys"] = expected_source_keys[:20]
    if source_key_match_applied:
        pre_filter_count = len(candidates)
        candidates = [c for c in candidates if _candidate_matches_source_keys(c, expected_source_keys)]
        meta["must_recall_source_key_match_applied"] = True
        meta["must_recall_source_key_match_candidates_before"] = int(pre_filter_count)
        meta["must_recall_source_key_match_candidates_after"] = int(len(candidates))
        if not candidates:
            meta["reason"] = "must_recall_source_key_miss"
            return [], meta

    min_score = int(getattr(settings, "CHAT_TAG_MIN_MATCH_SCORE", 1) or 1)
    best = max((c.score for c in candidates), default=0)
    if not intent and best < min_score:
        meta["reason"] = "no_intent_and_no_match"
        meta["best_score"] = int(best)
        return [], meta

    # Hardening: if we have table intent but *no* match signal and the scope is ambiguous (multiple docs/tables),
    # do not query a random table.
    if intent and best < min_score:
        unique_doc_ids = {c.document_id for c in candidates}
        if len(doc_ids) == 1:
            meta["selection_fallback"] = "single_document"
        elif len(candidates) == 1:
            meta["selection_fallback"] = "single_table"
        elif len(unique_doc_ids) == 1 and len(doc_ids) == 1:
            meta["selection_fallback"] = "single_document"
        else:
            meta["reason"] = "intent_no_match_ambiguous"
            meta["best_score"] = int(best)
            meta["candidates"] = int(len(candidates))
            meta["documents_with_tables"] = int(len(unique_doc_ids))
            return [], meta

    max_tables = int(getattr(settings, "CHAT_TAG_MAX_TABLES", 2) or 2)
    max_tables = max(0, min(max_tables, 5))
    high_conf = [c for c in candidates if int(c.score) >= int(min_score)]
    complex_query = bool(
        re.search(r"(?i)\b(join|group\s+by|by|per|across|between)\b|按|分组|关联|维度|同比|环比", str(question or ""))
    )
    effective_max_tables = int(max_tables)
    table_pick_policy = "default_cap"
    if effective_max_tables > 1 and complex_query and len(candidates) >= 2 and intent:
        effective_max_tables = min(effective_max_tables, 2)
        table_pick_policy = "complexity_schema_link_multi_table"
    elif not intent or len(high_conf) <= 1:
        effective_max_tables = min(effective_max_tables, 1)
        table_pick_policy = "single_table_low_complexity"

    candidates.sort(key=lambda c: (-int(c.score), -int(c.row_count), str(c.filename), str(c.table_id)))
    picked = candidates[:effective_max_tables] if effective_max_tables > 0 else []
    if not picked:
        meta["reason"] = "no_candidates_picked"
        return [], meta
    meta["table_pick_policy"] = table_pick_policy
    meta["effective_max_tables"] = int(effective_max_tables)

    # Query caps (bounded by server-level hard caps enforced by run_table_query as well).
    max_rows = int(getattr(settings, "CHAT_TAG_MAX_ROWS", 50) or 50)
    max_cols = int(getattr(settings, "CHAT_TAG_MAX_COLS", 30) or 30)
    max_bytes = int(getattr(settings, "CHAT_TAG_MAX_BYTES", 200_000) or 200_000)
    if max_rows <= 0:
        max_rows = 50
    if max_cols <= 0:
        max_cols = 30
    if max_bytes <= 10_000:
        max_bytes = 10_000

    # Multi-table deterministic JOIN path (same document only).
    if len(picked) >= 2:
        same_doc = len({c.document_id for c in picked}) == 1
        same_dataset = len({c.dataset_id for c in picked}) == 1
        if same_doc and same_dataset:
            join_inputs: list[dict[str, Any]] = []
            by_sql_table: dict[str, _TableCandidate] = {}
            for c in picked:
                sql_table = f"sheet_{int(c.sheet_index)}"
                by_sql_table[sql_table] = c
                join_inputs.append(
                    {
                        "table_name": sql_table,
                        "table_aliases": [c.table_id, c.filename, str(c.sheet_name or "")],
                        "columns": c.columns,
                        "row_count": int(c.row_count),
                        "sample_rows": c.sample_rows,
                    }
                )

            try:
                join_plan = plan_join_query_for_tables(
                    question=str(question or ""),
                    tables=join_inputs,
                    max_rows=max_rows,
                )
                join_sql = str(join_plan.get("sql") or "").strip()
                planner_diagnostics = join_plan.get("planner") if isinstance(join_plan, dict) else None
                planner_diagnostics = planner_diagnostics if isinstance(planner_diagnostics, dict) else {}
                join_provenance = planner_diagnostics.get("joins")
                if not isinstance(join_provenance, list):
                    join_provenance = []
                join_plan_risk = (
                    planner_diagnostics.get("join_plan_risk")
                    if isinstance(planner_diagnostics.get("join_plan_risk"), dict)
                    else None
                )
                sql_fingerprint = str(planner_diagnostics.get("sql_fingerprint") or "").strip() or fingerprint_sql(
                    join_sql, length=16
                )

                selected_sql_tables = [
                    str(t).strip()
                    for t in (planner_diagnostics.get("selected_tables") or [])
                    if str(t).strip()
                ]
                if not selected_sql_tables:
                    selected_sql_tables = list(by_sql_table.keys())[:2]
                selected_candidates = [by_sql_table[t] for t in selected_sql_tables if t in by_sql_table]
                if not selected_candidates:
                    selected_candidates = list(picked[:2])
                primary = selected_candidates[0]

                # Merge schema-link signals from selected tables for explainability.
                merged_cols: list[str] = []
                merged_vals: list[str] = []
                merged_tables: list[str] = []
                score_values: list[float] = []
                for c in selected_candidates:
                    diag = score_schema_link_diagnostics(
                        question=str(question or ""),
                        sql_table=f"sheet_{int(c.sheet_index)}",
                        columns=c.columns,
                        sample_rows=c.sample_rows,
                        table_aliases=[c.table_id, c.filename, str(c.sheet_name or "")],
                    )
                    for v in (diag.get("matched_columns") or []):
                        s = str(v or "").strip()
                        if s and s not in merged_cols:
                            merged_cols.append(s)
                    for v in (diag.get("matched_values") or []):
                        s = str(v or "").strip()
                        if s and s not in merged_vals:
                            merged_vals.append(s)
                    for v in (diag.get("matched_tables") or []):
                        s = str(v or "").strip()
                        if s and s not in merged_tables:
                            merged_tables.append(s)
                    try:
                        score_values.append(float(diag.get("score") or 0.0))
                    except Exception:
                        score_values.append(0.0)
                schema_link_diagnostics = {
                    "score": round(max(score_values) if score_values else 0.0, 3),
                    "strategy": "multi_table_join",
                    "reason": "joined_table_schema_overlap",
                    "matched_columns": merged_cols[:20],
                    "matched_values": merged_vals[:20],
                    "matched_tables": merged_tables[:20],
                }

                result = run_table_query(
                    tenant_id=tenant_id,
                    dataset_id=primary.dataset_id,
                    table_id=primary.table_id,
                    sql=join_sql,
                    max_rows=max_rows,
                    max_cols=max_cols,
                    max_bytes=max_bytes,
                    allowed_sql_tables=selected_sql_tables,
                    planner_diagnostics=planner_diagnostics,
                    expected_sql_fingerprint=sql_fingerprint,
                )
                planner_execution_mismatch = (
                    result.get("planner_execution_mismatch")
                    if isinstance(result.get("planner_execution_mismatch"), dict)
                    else None
                )
                mismatch_strict = bool(getattr(settings, "TABLE_TAG_PLANNER_MISMATCH_STRICT", False))
                if mismatch_strict and planner_execution_mismatch and bool(planner_execution_mismatch.get("mismatch")):
                    raise ValueError("planner_execution_mismatch")

                primary_source_key_match = _candidate_matches_source_keys(primary, expected_source_keys)
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
                    "join_table_ids": [c.table_id for c in selected_candidates],
                    "join_sql_tables": selected_sql_tables,
                    "must_recall_source_key_match": bool(primary_source_key_match),
                    "must_recall_expected_source_keys": expected_source_keys[:20],
                    "columns": result.get("columns") if isinstance(result.get("columns"), list) else [],
                    "rows": result.get("rows") if isinstance(result.get("rows"), list) else [],
                    "truncated": bool(result.get("truncated")),
                }
                text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                if len(text) > 12_000:
                    payload["rows"] = payload.get("rows", [])[:10]
                    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                    if len(text) > 12_000:
                        text = text[:12_000] + "..."

                doc = Document(
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
                        "join_plan_risk_selectivity_unknown": bool(
                            (join_plan_risk or {}).get("selectivity_unknown")
                        ),
                        "planner_execution_mismatch": planner_execution_mismatch,
                        "join_provenance": join_provenance,
                        "join_table_ids": [c.table_id for c in selected_candidates],
                        "join_sql_tables": selected_sql_tables,
                        "must_recall_source_key_match": bool(primary_source_key_match),
                        "must_recall_expected_source_keys": expected_source_keys[:20],
                        "score": 1.0,
                        "retrieval_score": 1.0,
                    },
                    id=str(_tag_doc_uuid(primary.table_id)),
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
                return [doc], meta
            except Exception as exc:  # noqa: BLE001
                meta["multi_table_error"] = str(exc)[:200]

    out_docs: list[Document] = []
    errors: list[str] = []
    for c in picked:
        sql_table = f"sheet_{int(c.sheet_index)}"
        try:
            schema_link_diagnostics = score_schema_link_diagnostics(
                question=str(question or ""),
                sql_table=sql_table,
                columns=c.columns,
                sample_rows=c.sample_rows,
                table_aliases=[c.table_id, c.filename, str(c.sheet_name or "")],
            )
            planner_diagnostics: dict[str, Any] | None = None
            sql_generation_mode = "llm"
            sql_fingerprint = ""
            has_llm_key = bool(str(getattr(settings, "LLM_API_KEY", "") or "").strip())
            deterministic_only = bool(getattr(settings, "TABLE_NL2SQL_DETERMINISTIC_ONLY", False))
            deterministic_fallback = bool(getattr(settings, "TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED", True))
            dbrows_sql_first = bool(
                getattr(settings, "CHAT_TAG_DBROWS_SQL_FIRST_ENABLED", True)
                and (
                    str(c.file_type or "").strip().lower() == "dbrows"
                    or str(c.source_ext or "").strip().lower() == ".dbrows"
                    or str(c.filename or "").strip().lower().endswith(".dbrows")
                )
            )
            source_key_match = _candidate_matches_source_keys(c, expected_source_keys)

            if deterministic_only or dbrows_sql_first or (not has_llm_key and deterministic_fallback):
                sql, sql_generation_mode, sql_meta = generate_sql_for_table_with_metadata(
                    question=str(question or ""),
                    sql_table=sql_table,
                    columns=c.columns,
                    max_rows=max_rows,
                    sample_rows=c.sample_rows,
                    table_aliases=[c.table_id, c.filename, str(c.sheet_name or "")],
                )
                if isinstance(sql_meta, dict):
                    linked = sql_meta.get("schema_link")
                    if isinstance(linked, dict):
                        schema_link_diagnostics = linked
                    planner = sql_meta.get("planner")
                    if isinstance(planner, dict):
                        planner_diagnostics = planner
                    planner_fp = ""
                    if isinstance(planner_diagnostics, dict):
                        planner_fp = str(planner_diagnostics.get("sql_fingerprint") or "").strip()
                    sql_fingerprint = str(sql_meta.get("sql_fingerprint") or planner_fp or "").strip()
            else:
                sql = generate_sql_for_table(
                    question=str(question or ""),
                    sql_table=sql_table,
                    columns=c.columns,
                    max_rows=max_rows,
                )
                planner_diagnostics = {"strategy": "llm", "reason": "llm_generation"}
            if not sql_fingerprint:
                sql_fingerprint = fingerprint_sql(sql, length=16)
            if isinstance(planner_diagnostics, dict):
                planner_diagnostics = dict(planner_diagnostics)
                planner_diagnostics.setdefault("sql_fingerprint", sql_fingerprint)
            join_plan_risk = (
                planner_diagnostics.get("join_plan_risk")
                if isinstance(planner_diagnostics, dict) and isinstance(planner_diagnostics.get("join_plan_risk"), dict)
                else None
            )

            result = run_table_query(
                tenant_id=tenant_id,
                dataset_id=c.dataset_id,
                table_id=c.table_id,
                sql=sql,
                max_rows=max_rows,
                max_cols=max_cols,
                max_bytes=max_bytes,
                planner_diagnostics=planner_diagnostics,
                expected_sql_fingerprint=sql_fingerprint,
            )
            planner_execution_mismatch = (
                result.get("planner_execution_mismatch")
                if isinstance(result.get("planner_execution_mismatch"), dict)
                else None
            )
            mismatch_strict = bool(getattr(settings, "TABLE_TAG_PLANNER_MISMATCH_STRICT", False))
            if mismatch_strict and planner_execution_mismatch and bool(planner_execution_mismatch.get("mismatch")):
                raise ValueError("planner_execution_mismatch")
            payload = {
                "kind": "tag_table_store",
                "document": c.filename,
                "table_id": c.table_id,
                "sheet_index": int(c.sheet_index),
                "sheet_name": c.sheet_name,
                "row_count": int(c.row_count),
                "col_count": int(c.col_count),
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

            if c.row_source_table or c.row_source_sync_token or c.row_source_pk_hash_col:
                row_source: dict[str, Any] = {}
                if c.row_source_table:
                    row_source["table"] = c.row_source_table
                if c.row_source_sync_token:
                    row_source["sync_token"] = c.row_source_sync_token
                pk_hash_col = str(c.row_source_pk_hash_col or "__row_pk_hash").strip() or "__row_pk_hash"
                col_names = payload.get("columns") if isinstance(payload.get("columns"), list) else []
                rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
                if pk_hash_col in col_names and rows:
                    idx_pk = col_names.index(pk_hash_col)
                    pk_hashes: list[str] = []
                    for row in rows:
                        if not isinstance(row, list) or idx_pk >= len(row):
                            continue
                        val = str(row[idx_pk] or "").strip()
                        if not val or val in pk_hashes:
                            continue
                        pk_hashes.append(val)
                        if len(pk_hashes) >= 200:
                            break
                    if pk_hashes:
                        row_source["pk_hashes"] = pk_hashes
                if row_source:
                    payload["row_source"] = row_source
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            # Keep each injected context doc bounded.
            max_doc_chars = 12_000
            if len(text) > max_doc_chars:
                # Drop rows first (keep schema + sql).
                payload["rows"] = payload.get("rows", [])[:10]
                text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                if len(text) > max_doc_chars:
                    text = text[:max_doc_chars] + "..."

            out_docs.append(
                Document(
                    page_content=text,
                    metadata={
                        "document_id": c.document_id,
                        "source": c.filename or "table",
                        "retrieval_role": "tag",
                        "chunk_strategy": "tag",
                        "chunk_role": "tag_sql_result",
                        "table_id": c.table_id,
                        "sheet_index": int(c.sheet_index),
                        "sheet_name": c.sheet_name,
                        "sql_fingerprint": sql_fingerprint,
                        "sql_generation_mode": sql_generation_mode,
                        "schema_link_score": (
                            schema_link_diagnostics.get("score")
                            if isinstance(schema_link_diagnostics, dict)
                            else None
                        ),
                        "schema_link_strategy": (
                            schema_link_diagnostics.get("strategy")
                            if isinstance(schema_link_diagnostics, dict)
                            else None
                        ),
                        "schema_link_reason": (
                            schema_link_diagnostics.get("reason")
                            if isinstance(schema_link_diagnostics, dict)
                            else None
                        ),
                        "schema_link_diagnostics": schema_link_diagnostics,
                        "planner_diagnostics": planner_diagnostics,
                        "join_plan_risk": join_plan_risk,
                        "join_plan_risk_fanout_explosive": bool((join_plan_risk or {}).get("fanout_explosive")),
                        "join_plan_risk_selectivity_unknown": bool((join_plan_risk or {}).get("selectivity_unknown")),
                        "planner_execution_mismatch": planner_execution_mismatch,
                        "must_recall_source_key_match": bool(source_key_match),
                        "must_recall_expected_source_keys": expected_source_keys[:20],
                        "row_source_table": (
                            payload.get("row_source", {}).get("table")
                            if isinstance(payload.get("row_source"), dict)
                            else c.row_source_table
                        ),
                        "row_source_sync_token": (
                            payload.get("row_source", {}).get("sync_token")
                            if isinstance(payload.get("row_source"), dict)
                            else c.row_source_sync_token
                        ),
                        "row_source_pk_hashes": (
                            payload.get("row_source", {}).get("pk_hashes")
                            if isinstance(payload.get("row_source"), dict)
                            else None
                        ),
                        # Treat as strong evidence for abstain guard (not comparable to vector scores).
                        "score": 1.0,
                        "retrieval_score": 1.0,
                    },
                    # Must be UUID-like for ChatResponse citation schema compatibility.
                    id=str(_tag_doc_uuid(c.table_id)),
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{c.table_id}:{str(exc)[:160]}")
            continue

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


__all__ = ["build_chat_tag_context_docs"]
