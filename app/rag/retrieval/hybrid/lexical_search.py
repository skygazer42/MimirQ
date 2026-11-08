"""Lexical and metadata-anchor SQL queries with explicit scope and transaction ownership."""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import Text as SQLText
from sqlalchemy import case, func, or_, text
from sqlalchemy import cast as sql_cast
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.filters import match_metadata_filter
from app.rag.preprocessing.tokenization import tokenize_lexical_text
from app.rag.retrieval.hybrid.common import (
    _metadata_exact_anchor_match,
    _query_looks_like_cjk_metadata_anchor,
    logger,
)
from app.rag.retrieval.hybrid.metadata_scope import lexical_dataset_scope
from app.rag.retrieval.hybrid.runtime_scope import RetrievalScope, with_dataset_scope_filter


@dataclass(frozen=True)
class LexicalRequest:
    query: str
    top_k: int
    scope: RetrievalScope


@dataclass(frozen=True)
class LexicalOutcome:
    records: list[dict[str, Any]]
    pg_trgm_available: bool | None
    failure: Exception | None = None


@dataclass
class _LexicalRun:
    pg_trgm_available: bool | None
    records: dict[str, dict[str, Any]] = field(default_factory=dict)


def _lexical_search_config(top_k: int) -> tuple[str, int, bool, int]:
    fts_config = (settings.LEXICAL_DB_FTS_CONFIG or "simple").strip() or "simple"
    fetch_mult = max(1, settings.LEXICAL_DB_FETCH_MULTIPLIER or 4)
    fetch_cap = max(10, settings.LEXICAL_DB_MAX_CANDIDATES or 200)
    limit = max(0, top_k)
    fetch_k = min(fetch_cap, max(limit, limit * fetch_mult))
    want_trgm = settings.LEXICAL_DB_TRGM_ENABLED
    trgm_min_chars = max(1, settings.LEXICAL_DB_TRGM_MIN_QUERY_CHARS or 3)
    return (fts_config, fetch_k, want_trgm, trgm_min_chars)


def _lexical_cjk_token_terms(raw_query: str) -> list[str]:
    text = raw_query.strip()
    if not text or not re.search("[\\u3400-\\u4dbf\\u4e00-\\u9fff]", text):
        return []
    max_terms = max(1, min(16, settings.LEXICAL_DB_CJK_TOKEN_MAX_TERMS or 6))
    candidates: list[str] = []
    seen: set[str] = set()
    for token in tokenize_lexical_text(text):
        term = token.strip()
        if len(term) < 2:
            continue
        # Codes, years and IDs inside CJK queries remain useful exact constraints.
        if not re.search("[\\u3400-\\u4dbf\\u4e00-\\u9fff0-9A-Za-z]", term):
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(term)
    selected: list[str] = []
    for term in sorted(candidates, key=lambda item: (-len(item), candidates.index(item))):
        folded = term.casefold()
        if any((folded in existing.casefold() for existing in selected)):
            continue
        selected.append(term)
        if len(selected) >= max_terms:
            break
    return selected


def _lexical_base_query(
    db: Session, *, tenant_uuid: UUID, dataset_uuid: UUID | list[UUID] | None, document_ids: list[UUID] | None
) -> Any:
    query = (
        db.query(
            DocumentChunk.id,
            DocumentChunk.content,
            DocumentChunk.doc_metadata,
            DocumentChunk.tenant_id,
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            DocumentChunk.page_number,
            DBDocument.dataset_id,
        )
        .join(DBDocument, DocumentChunk.document_id == DBDocument.id)
        .filter(DBDocument.status == "completed")
        .filter(DBDocument.publication_status == "published")
        .filter(DBDocument.archived_at.is_(None))
        .filter(DBDocument.disabled_at.is_(None))
        .filter(DocumentChunk.disabled_at.is_(None))
        .filter(DocumentChunk.tenant_id == tenant_uuid)
    )
    if isinstance(dataset_uuid, list):
        if len(dataset_uuid) == 1:
            query = query.filter(DBDocument.dataset_id == dataset_uuid[0])
        elif dataset_uuid:
            query = query.filter(DBDocument.dataset_id.in_(dataset_uuid))
    elif dataset_uuid is not None:
        query = query.filter(DBDocument.dataset_id == dataset_uuid)
    if document_ids:
        query = query.filter(DocumentChunk.document_id.in_(document_ids))
    return query


def _lexical_result_from_row(
    row: Any, *, method: str, dataset_str: str | None, metadata_filter: dict[str, Any] | None
) -> tuple[str, dict[str, Any]] | None:
    (
        chunk_id,
        content,
        doc_metadata,
        tenant_uuid_row,
        document_uuid_row,
        chunk_index,
        page_number,
        dataset_uuid_row,
        score_raw,
    ) = tuple(row)
    cid = str(chunk_id)
    score = float(score_raw or 0.0)
    meta = dict(doc_metadata or {})
    meta.setdefault("tenant_id", str(tenant_uuid_row))
    meta.setdefault("document_id", str(document_uuid_row))
    meta.setdefault("chunk_index", int(chunk_index) if chunk_index is not None else None)
    meta.setdefault("chunk_id", cid)
    meta.setdefault("source", meta.get("source", "unknown"))
    effective_dataset_str = str(dataset_uuid_row) if dataset_uuid_row is not None else dataset_str
    if effective_dataset_str:
        meta.setdefault("dataset_id", effective_dataset_str)
    if page_number is not None and (not meta.get("page")):
        meta["page"] = page_number
    meta.setdefault("lexical_method", method)
    meta.setdefault("lexical_score_raw", score)
    if metadata_filter and (not match_metadata_filter(meta, metadata_filter)):
        return None
    return (cid, {"chunk_id": cid, "content": content or "", "metadata": meta, "score": score})


def _add_lexical_rows(
    *,
    rows: Any,
    results_by_id: dict[str, dict[str, Any]],
    method: str,
    dataset_str: str | None,
    metadata_filter: dict[str, Any] | None,
    replace_if_higher: bool = False,
) -> None:
    for row in rows:
        parsed = _lexical_result_from_row(row, method=method, dataset_str=dataset_str, metadata_filter=metadata_filter)
        if parsed is None:
            continue
        cid, result = parsed
        existing = results_by_id.get(cid)
        if (
            not replace_if_higher
            or existing is None
            or float(existing.get("score", 0.0) or 0.0) < float(result.get("score", 0.0) or 0.0)
        ):
            results_by_id[cid] = result


def _collect_lexical_fts_results(
    *,
    db: Session,
    tenant_uuid: UUID,
    dataset_uuid: UUID | list[UUID] | None,
    document_ids: list[UUID] | None,
    fts_config: str,
    raw_query: str,
    fetch_k: int,
    method: str,
    tsquery_builder: Any,
    dataset_str: str | None,
    metadata_filter: dict[str, Any] | None,
    results_by_id: dict[str, dict[str, Any]],
) -> None:
    vector = func.to_tsvector(fts_config, DocumentChunk.content)
    tsq = tsquery_builder(fts_config, raw_query)
    rank = func.ts_rank_cd(vector, tsq).label("fts_rank")
    rows = (
        _lexical_base_query(db, tenant_uuid=tenant_uuid, dataset_uuid=dataset_uuid, document_ids=document_ids)
        .add_columns(rank)
        .filter(vector.op("@@")(tsq))
        .order_by(rank.desc())
        .limit(fetch_k)
        .all()
    )
    _add_lexical_rows(
        rows=rows, results_by_id=results_by_id, method=method, dataset_str=dataset_str, metadata_filter=metadata_filter
    )


def _lexical_pg_trgm_available_now(db: Session, *, run: _LexicalRun) -> bool:
    pg_trgm_available = run.pg_trgm_available
    if pg_trgm_available is not None:
        return bool(pg_trgm_available)
    row = db.execute(text("SELECT 1 FROM pg_extension WHERE extname='pg_trgm' LIMIT 1;")).first()
    pg_trgm_available = bool(row)
    run.pg_trgm_available = pg_trgm_available
    return bool(pg_trgm_available)


def _collect_lexical_trigram_results(
    *,
    db: Session,
    tenant_uuid: UUID,
    dataset_uuid: UUID | list[UUID] | None,
    document_ids: list[UUID] | None,
    raw_query: str,
    fetch_k: int,
    dataset_str: str | None,
    metadata_filter: dict[str, Any] | None,
    results_by_id: dict[str, dict[str, Any]],
) -> None:
    sim = func.similarity(DocumentChunk.content, raw_query).label("trgm_sim")
    rows = (
        _lexical_base_query(db, tenant_uuid=tenant_uuid, dataset_uuid=dataset_uuid, document_ids=document_ids)
        .add_columns(sim)
        .filter(DocumentChunk.content.op("%")(raw_query))
        .order_by(sim.desc())
        .limit(fetch_k)
        .all()
    )
    _add_lexical_rows(
        rows=rows,
        results_by_id=results_by_id,
        method="trgm",
        dataset_str=dataset_str,
        metadata_filter=metadata_filter,
        replace_if_higher=True,
    )


def _collect_lexical_cjk_token_results(
    *,
    db: Session,
    tenant_uuid: UUID,
    dataset_uuid: UUID | list[UUID] | None,
    document_ids: list[UUID] | None,
    raw_query: str,
    fetch_k: int,
    dataset_str: str | None,
    metadata_filter: dict[str, Any] | None,
    results_by_id: dict[str, dict[str, Any]],
) -> None:
    if not settings.LEXICAL_DB_CJK_TOKEN_CONTAINMENT_ENABLED:
        return
    terms = _lexical_cjk_token_terms(raw_query)
    if not terms:
        return
    conditions = []
    score_expr = None
    hit_expr = None
    for term in terms:
        pattern = f"%{_escape_sql_like_term(term)}%"
        condition = DocumentChunk.content.ilike(pattern, escape="\\")
        conditions.append(condition)
        score_piece = case((condition, float(len(term))), else_=0.0)
        hit_piece = case((condition, 1), else_=0)
        score_expr = score_piece if score_expr is None else score_expr + score_piece
        hit_expr = hit_piece if hit_expr is None else hit_expr + hit_piece
    if not conditions or score_expr is None or hit_expr is None:
        return
    configured_min_hits = settings.LEXICAL_DB_CJK_TOKEN_MIN_HITS
    min_hits = configured_min_hits
    if min_hits <= 0:
        min_hits = min(3, max(1, len(terms) // 2))
    rows = (
        _lexical_base_query(db, tenant_uuid=tenant_uuid, dataset_uuid=dataset_uuid, document_ids=document_ids)
        .add_columns(score_expr.label("cjk_token_score"))
        .filter(or_(*conditions))
        .filter(hit_expr >= min_hits)
        .order_by(score_expr.desc(), DocumentChunk.chunk_index.asc())
        .limit(fetch_k)
        .all()
    )
    _add_lexical_rows(
        rows=rows,
        results_by_id=results_by_id,
        method="cjk_token",
        dataset_str=dataset_str,
        metadata_filter=metadata_filter,
        replace_if_higher=True,
    )


def _search_lexical_db_with_session(
    *,
    db: Session,
    raw_query: str,
    top_k: int,
    tenant_uuid: UUID,
    document_ids: list[UUID] | None = None,
    metadata_filter: dict[str, Any] | None = None,
    run: _LexicalRun,
) -> list[dict[str, Any]]:
    dataset_uuid, dataset_str = lexical_dataset_scope(metadata_filter)
    fts_config, fetch_k, want_trgm, trgm_min_chars = _lexical_search_config(top_k)
    limit = max(0, top_k)
    if limit <= 0:
        return []
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return []
    results_by_id: dict[str, dict[str, Any]] = run.records
    _collect_lexical_fts_results(
        db=db,
        tenant_uuid=tenant_uuid,
        dataset_uuid=dataset_uuid,
        document_ids=document_ids,
        fts_config=fts_config,
        raw_query=raw_query,
        fetch_k=fetch_k,
        method="fts",
        tsquery_builder=func.websearch_to_tsquery,
        dataset_str=dataset_str,
        metadata_filter=metadata_filter,
        results_by_id=results_by_id,
    )
    if not results_by_id:
        _collect_lexical_fts_results(
            db=db,
            tenant_uuid=tenant_uuid,
            dataset_uuid=dataset_uuid,
            document_ids=document_ids,
            fts_config=fts_config,
            raw_query=raw_query,
            fetch_k=fetch_k,
            method="fts_plain",
            tsquery_builder=func.plainto_tsquery,
            dataset_str=dataset_str,
            metadata_filter=metadata_filter,
            results_by_id=results_by_id,
        )
    if want_trgm and len(raw_query) >= trgm_min_chars and _lexical_pg_trgm_available_now(db, run=run):
        _collect_lexical_trigram_results(
            db=db,
            tenant_uuid=tenant_uuid,
            dataset_uuid=dataset_uuid,
            document_ids=document_ids,
            raw_query=raw_query,
            fetch_k=fetch_k,
            dataset_str=dataset_str,
            metadata_filter=metadata_filter,
            results_by_id=results_by_id,
        )
    _collect_lexical_cjk_token_results(
        db=db,
        tenant_uuid=tenant_uuid,
        dataset_uuid=dataset_uuid,
        document_ids=document_ids,
        raw_query=raw_query,
        fetch_k=fetch_k,
        dataset_str=dataset_str,
        metadata_filter=metadata_filter,
        results_by_id=results_by_id,
    )
    if not results_by_id:
        return []
    merged = list(results_by_id.values())
    merged.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
    return merged[:limit]


def _escape_sql_like_term(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _metadata_exact_db_like_terms(value: str) -> list[str]:
    raw = value.strip()
    if not raw:
        return []
    variants: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        item = text.strip()
        if not item or item in seen:
            return
        seen.add(item)
        variants.append(item)

    add(raw)
    add(unicodedata.normalize("NFKC", raw))
    for item in list(variants):
        add(item.translate(str.maketrans({"(": "（", ")": "）"})))
        add(item.translate(str.maketrans({"（": "(", "）": ")"})))
    return variants


def _metadata_exact_result_from_row(
    row: Any, *, query: str, dataset_str: str | None, metadata_filter: dict[str, Any] | None
) -> tuple[str, dict[str, Any]] | None:
    chunk_id, content, doc_metadata, tenant_uuid_row, document_uuid_row, chunk_index, page_number, dataset_uuid_row = (
        tuple(row)
    )
    meta = dict(doc_metadata or {})
    metadata_match = _metadata_exact_anchor_match(query, meta)
    if not metadata_match:
        return None
    cid = str(chunk_id)
    match_score = float(metadata_match.get("score") or 0.0)
    meta.setdefault("tenant_id", str(tenant_uuid_row))
    meta.setdefault("document_id", str(document_uuid_row))
    meta.setdefault("chunk_index", int(chunk_index) if chunk_index is not None else None)
    meta.setdefault("chunk_id", cid)
    meta.setdefault("source", meta.get("source", "unknown"))
    effective_dataset_str = str(dataset_uuid_row) if dataset_uuid_row is not None else dataset_str
    if effective_dataset_str:
        meta.setdefault("dataset_id", effective_dataset_str)
    if page_number is not None and (not meta.get("page")):
        meta["page"] = page_number
    meta.setdefault("lexical_method", "metadata_exact")
    meta["metadata_exact_candidate"] = True
    meta["metadata_exact_candidate_field"] = str(metadata_match.get("field") or "")
    meta["metadata_exact_candidate_fields"] = list(metadata_match.get("fields") or [])
    meta["metadata_exact_candidate_score"] = float(match_score)
    if metadata_filter and (not match_metadata_filter(meta, metadata_filter)):
        return None
    return (cid, {"chunk_id": cid, "content": content or "", "metadata": meta, "score": max(1.0, float(match_score))})


def _search_metadata_exact_anchor_db_with_session(
    *,
    db: Session,
    query: str,
    top_k: int,
    tenant_uuid: UUID,
    document_ids: list[UUID] | None = None,
    metadata_filter: dict[str, Any] | None = None,
    run: _LexicalRun,
) -> list[dict[str, Any]]:
    raw_query = query.strip()
    if not raw_query or not _query_looks_like_cjk_metadata_anchor(raw_query):
        return []
    dataset_uuid, dataset_str = lexical_dataset_scope(metadata_filter)
    limit = max(1, top_k)
    cap = max(1, settings.RETRIEVAL_METADATA_EXACT_DB_MAX_CANDIDATES or 80)
    fetch_k = min(cap, max(limit, limit * 4))
    patterns = [f"%{_escape_sql_like_term(term)}%" for term in _metadata_exact_db_like_terms(raw_query)]
    if not patterns:
        return []
    metadata_text = sql_cast(DocumentChunk.doc_metadata, SQLText)
    metadata_predicate = (
        metadata_text.ilike(patterns[0], escape="\\")
        if len(patterns) == 1
        else or_(*(metadata_text.ilike(pattern, escape="\\") for pattern in patterns))
    )
    rows = (
        _lexical_base_query(db, tenant_uuid=tenant_uuid, dataset_uuid=dataset_uuid, document_ids=document_ids)
        .filter(metadata_predicate)
        .limit(fetch_k)
        .all()
    )
    results_by_id: dict[str, dict[str, Any]] = run.records
    for row in rows:
        parsed = _metadata_exact_result_from_row(
            row, query=raw_query, dataset_str=dataset_str, metadata_filter=metadata_filter
        )
        if parsed is None:
            continue
        cid, result = parsed
        results_by_id[cid] = result
    if not results_by_id:
        return []
    results = list(results_by_id.values())
    results.sort(
        key=lambda item: (
            -float((item.get("metadata") or {}).get("metadata_exact_candidate_score") or 0.0),
            str(item.get("chunk_id") or ""),
        )
    )
    return results[:limit]


def search_lexical(db: Session, request: LexicalRequest, *, pg_trgm_available: bool | None = None) -> LexicalOutcome:
    run = _LexicalRun(pg_trgm_available)
    raw_query = request.query.strip()
    if not raw_query or not settings.LEXICAL_DB_ENABLED:
        return LexicalOutcome([], run.pg_trgm_available)
    try:
        if request.scope.tenant_id is None:
            raise ValueError("Lexical query requires tenant_id")
        records = _search_lexical_db_with_session(
            db=db,
            raw_query=raw_query,
            top_k=request.top_k,
            tenant_uuid=request.scope.tenant_id,
            document_ids=list(request.scope.document_ids) if request.scope.document_ids else None,
            metadata_filter=_effective_filter(request),
            run=run,
        )
        return LexicalOutcome(records, run.pg_trgm_available)
    except Exception as exc:
        logger.debug("Lexical query failed: %s", exc)
        records = sorted(run.records.values(), key=lambda item: -float(item["score"]))[: max(0, request.top_k)]
        return LexicalOutcome(records, run.pg_trgm_available, exc)


def search_metadata_exact(db: Session, request: LexicalRequest, *, enabled: bool) -> LexicalOutcome:
    run = _LexicalRun(None)
    if not request.query.strip() or not enabled:
        return LexicalOutcome([], None)
    try:
        if request.scope.tenant_id is None:
            raise ValueError("Lexical query requires tenant_id")
        if db.get_bind().dialect.name != "postgresql":
            return LexicalOutcome([], None)
        records = _search_metadata_exact_anchor_db_with_session(
            db=db,
            query=request.query,
            top_k=request.top_k,
            tenant_uuid=request.scope.tenant_id,
            document_ids=list(request.scope.document_ids) if request.scope.document_ids else None,
            metadata_filter=_effective_filter(request),
            run=run,
        )
        return LexicalOutcome(records, None)
    except Exception as exc:
        logger.debug("Metadata exact DB fallback failed: %s", exc)
        return LexicalOutcome([], None, exc)


def _effective_filter(request: LexicalRequest) -> dict[str, Any] | None:
    return with_dataset_scope_filter(request.scope.metadata_filter, dataset_ids=request.scope.dataset_ids)
