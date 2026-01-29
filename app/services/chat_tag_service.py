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

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.services.table_store_service import run_table_query
from app.services.table_tag_service import generate_sql_for_table

_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{1,}|[\u4e00-\u9fff]{2,}")
_TABLE_INTENT_RE = re.compile(
    r"(?i)\b(select|where|group\s+by|order\s+by|limit|sum|avg|count|min|max|distinct)\b"
    r"|统计|汇总|求和|平均|最大|最小|排名|Top\s*\d+|前\s*\d+|多少|几条|筛选|过滤|分组|占比"
)


@dataclass(frozen=True)
class _TableCandidate:
    document_id: UUID
    dataset_id: UUID
    filename: str
    table_id: str
    sheet_index: int
    sheet_name: Optional[str]
    row_count: int
    col_count: int
    columns: list[dict[str, Any]]
    score: int


def _enabled_reason() -> tuple[bool, str]:
    if not bool(getattr(settings, "CHAT_TAG_ENABLED", False)):
        return False, "CHAT_TAG_ENABLED=false"
    if not bool(getattr(settings, "TABLE_NL2SQL_ENABLED", False)):
        return False, "TABLE_NL2SQL_ENABLED=false"
    if not bool(getattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", False)):
        # Chat will inject query results into the LLM context; treat this as "result egress".
        return False, "TABLE_LLM_ALLOW_RESULT_EGRESS=false"
    if not str(getattr(settings, "LLM_API_KEY", "") or "").strip():
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
    sheet_name: Optional[str],
    columns: list[dict[str, Any]],
) -> int:
    if not terms:
        return 0
    score = 0
    fn = filename or ""
    sn = sheet_name or ""
    col_names = [str(c.get("name") or "") for c in (columns or []) if isinstance(c, dict)]

    for t in terms:
        if _match_score(fn, t):
            score += 3
            continue
        if sn and _match_score(sn, t):
            score += 4
            continue
        if any(_match_score(cn, t) for cn in col_names[:2000]):
            score += 1
            continue
    return int(score)


def build_chat_tag_context_docs(
    db: Session,
    *,
    tenant_id: UUID,
    document_ids: list[UUID],
    question: str,
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
            DBDocument.file_type.in_(["csv", "xls", "xlsx"]),
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
        md = getattr(d, "doc_metadata", None) or {}
        md = md if isinstance(md, dict) else {}
        store = md.get("table_store")
        if not isinstance(store, dict):
            continue
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

            score = _score_candidate(terms=terms, filename=filename, sheet_name=sheet_name, columns=cols_list)
            candidates.append(
                _TableCandidate(
                    document_id=d.id,
                    dataset_id=dataset_id,
                    filename=filename,
                    table_id=table_id,
                    sheet_index=sheet_index,
                    sheet_name=sheet_name,
                    row_count=row_count,
                    col_count=col_count,
                    columns=cols_list,
                    score=score,
                )
            )

    if not candidates:
        meta["reason"] = "no_table_assets"
        return [], meta

    min_score = int(getattr(settings, "CHAT_TAG_MIN_MATCH_SCORE", 1) or 1)
    best = max((c.score for c in candidates), default=0)
    if not intent and best < min_score:
        meta["reason"] = "no_intent_and_no_match"
        meta["best_score"] = int(best)
        return [], meta

    max_tables = int(getattr(settings, "CHAT_TAG_MAX_TABLES", 2) or 2)
    max_tables = max(0, min(max_tables, 5))

    candidates.sort(key=lambda c: (-int(c.score), -int(c.row_count), str(c.filename), str(c.table_id)))
    picked = candidates[:max_tables] if max_tables > 0 else []
    if not picked:
        meta["reason"] = "no_candidates_picked"
        return [], meta

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

    out_docs: list[Document] = []
    errors: list[str] = []
    for c in picked:
        sql_table = f"sheet_{int(c.sheet_index)}"
        try:
            sql = generate_sql_for_table(
                question=str(question or ""),
                sql_table=sql_table,
                columns=c.columns,
                max_rows=max_rows,
            )
            result = run_table_query(
                tenant_id=tenant_id,
                dataset_id=c.dataset_id,
                table_id=c.table_id,
                sql=sql,
                max_rows=max_rows,
                max_cols=max_cols,
                max_bytes=max_bytes,
            )
            payload = {
                "kind": "tag_table_store",
                "document": c.filename,
                "table_id": c.table_id,
                "sheet_index": int(c.sheet_index),
                "sheet_name": c.sheet_name,
                "row_count": int(c.row_count),
                "col_count": int(c.col_count),
                "sql": str(result.get("sql") or sql),
                "columns": result.get("columns") if isinstance(result.get("columns"), list) else [],
                "rows": result.get("rows") if isinstance(result.get("rows"), list) else [],
                "truncated": bool(result.get("truncated")),
            }
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
                        # Treat as strong evidence for abstain guard (not comparable to vector scores).
                        "score": 1.0,
                        "retrieval_score": 1.0,
                    },
                    id=f"tag:{c.table_id}",
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

