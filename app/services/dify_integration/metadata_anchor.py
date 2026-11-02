"""Metadata anchor retrieval, database eligibility and deadline/session policy."""

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Text as SQLText
from sqlalchemy import and_, or_
from sqlalchemy import cast as sql_cast
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document, DocumentChunk
from app.rag.core.logging import get_logger
from app.rag.retrieval.plugin_policy import record_retrieval_policy_bonus
from app.services.dify_integration import (
    answer_hints,
    common,
    policy_helpers,
    query_policy,
    record_processing,
    record_ranking,
)
from app.services.dify_integration.anchor_strength import _query_intent_terms as _query_intent_terms
from app.services.dify_integration.anchor_strength import (
    _record_is_composite_exact_anchor_answer as _record_is_composite_exact_anchor_answer,
)
from app.services.dify_integration.common import _CJK_RE as _CJK_RE
from app.services.dify_integration.common import (
    _METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS as _METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS,
)
from app.services.dify_integration.common import _MIN_SPECIFIC_INTENT_CHARS as _MIN_SPECIFIC_INTENT_CHARS
from app.services.dify_integration.common import (
    _QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH as _QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH,
)
from app.services.dify_integration.common import _iter_record_metadata_layers as _iter_record_metadata_layers
from app.services.dify_integration.common import _normalize_match_term as _normalize_match_term
from app.services.dify_integration.policy_helpers import record_plugin_ref as _record_plugin_ref
from app.services.dify_integration.query_terms import (
    _metadata_anchor_service_name_query_terms as _metadata_anchor_service_name_query_terms,
)
from app.services.dify_integration.query_terms import (
    _query_has_specific_service_anchor_candidate as _query_has_specific_service_anchor_candidate,
)
from app.services.dify_integration.records import _coerce_uuid_text as _coerce_uuid_text
from app.services.dify_integration.records import _row_value as _row_value
from app.services.dify_integration.scoring import _contains_cjk as _contains_cjk
from app.services.dify_integration.scoring import _diagnostic_query_hash as _diagnostic_query_hash
from app.services.dify_integration.scoring import _iter_anchor_word_segments as _iter_anchor_word_segments
from app.services.dify_integration.scoring import (
    _query_has_quoted_anchor_candidate as _query_has_quoted_anchor_candidate,
)
from app.services.dify_integration.scoring import _quoted_query_anchor_terms as _quoted_query_anchor_terms
from app.services.dify_integration.scoring import _record_metadata_anchor_bonus as _record_metadata_anchor_bonus
from app.services.rag_runtime_limiter import run_blocking_retrieval_call

logger = get_logger(__name__)

_METADATA_ANCHOR_DB_FALLBACK_MIN_SCORE = 0.72

_METADATA_ANCHOR_DB_FALLBACK_DEFAULT_SCORE = 0.74

_METADATA_ANCHOR_DB_FALLBACK_MAX_QUERY_TERMS = 12

_METADATA_ANCHOR_DB_FALLBACK_ARRAY_FIELDS = (
    "retrieval_intents",
    "query_intents",
    "intent_terms",
    "aliases",
    "service_aliases",
    "keywords",
    "semantic_keys",
)

_METADATA_ANCHOR_DB_FALLBACK_SCALAR_FIELDS = (
    "question",
    "service_name",
    "primary_alias",
    "case_title",
    "source_topic",
    "title",
)

_METADATA_ANCHOR_DB_FALLBACK_TITLE_FIELDS = ("case_title", "source_topic", "title")


def _metadata_anchor_fallback_query_terms(query: str) -> list[str]:
    text = str(query or "").strip()
    if not text:
        return []

    terms: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        term = str(raw or "").strip()
        normalized = _normalize_match_term(term)
        if len(normalized) < 4 or normalized in seen:
            return
        seen.add(normalized)
        terms.append(term)

    for segment in _iter_anchor_word_segments(text):
        add(segment)
        if not _contains_cjk(segment):
            continue
        for start in range(0, len(segment)):
            for size in (6, 4):
                if start + size > len(segment):
                    continue
                add(segment[start : start + size])
                if len(terms) >= _METADATA_ANCHOR_DB_FALLBACK_MAX_QUERY_TERMS:
                    return terms
    return terms[:_METADATA_ANCHOR_DB_FALLBACK_MAX_QUERY_TERMS]


def _query_has_specific_fast_metadata_anchor_candidate(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    if _query_has_specific_service_anchor_candidate(query, policy_plugin_refs=policy_plugin_refs):
        return True
    if not _query_has_quoted_anchor_candidate(query):
        return False
    for term in _quoted_query_anchor_terms(query):
        normalized = _normalize_match_term(term)
        if not _CJK_RE.search(normalized):
            continue
        if _MIN_SPECIFIC_INTENT_CHARS <= len(normalized) <= 50:
            return True
    return False


def _metadata_anchor_fallback_record_score(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    content = str(record.get("content") or "").strip()
    if content and record_ranking._record_is_anchor_only_qa(
        record, content=content, policy_plugin_refs=policy_plugin_refs
    ):
        return 0.0
    question_strength = record_ranking._record_question_anchor_strength(
        record,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    anchor_bonus = _record_metadata_anchor_bonus(record, query=query)
    intent_bonus = record_ranking._record_intent_bonus(record, query=query, policy_plugin_refs=policy_plugin_refs)
    policy_bonus = record_retrieval_policy_bonus(
        record,
        query=query,
        plugin_ref_for_record=lambda item: _record_plugin_ref(item, fallback_plugin_refs=policy_plugin_refs),
        metadata_layers_for_record=_iter_record_metadata_layers,
        policy_resolver=policy_helpers.retrieval_policy_for_plugin_ref,
    )
    has_strong_question_anchor = record_ranking._record_has_strong_question_anchor(
        record,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    if question_strength >= _QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH and not has_strong_question_anchor:
        return 0.0
    if has_strong_question_anchor:
        base = 0.86 + min(0.1, question_strength * 0.1)
    elif anchor_bonus >= 0.08:
        base = _METADATA_ANCHOR_DB_FALLBACK_DEFAULT_SCORE
    else:
        return 0.0
    score = base + max(0.0, anchor_bonus) + max(0.0, intent_bonus) + max(0.0, policy_bonus)
    return round(min(0.99, max(_METADATA_ANCHOR_DB_FALLBACK_MIN_SCORE, score)), 6)


def _metadata_anchor_fallback_records_from_rows(
    rows: list[Any] | tuple[Any, ...],
    *,
    dataset_ids: list[UUID] | tuple[UUID, ...],
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
    existing_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if record_ranking._records_can_skip_metadata_anchor_fallback(
        existing_records or [],
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return []

    scoped_dataset_ids = {str(dataset_id) for dataset_id in dataset_ids}
    if not scoped_dataset_ids:
        return []

    candidates = _metadata_anchor_fallback_candidate_records(
        rows,
        scoped_dataset_ids=scoped_dataset_ids,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )

    if not candidates:
        return []
    record_ranking._sort_records_for_query(candidates, query=query, policy_plugin_refs=policy_plugin_refs)
    composite = _metadata_anchor_exact_slot_composite(
        candidates,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    if composite is not None:
        return [composite]
    merged = record_ranking._dedupe_records(candidates, query=query, policy_plugin_refs=policy_plugin_refs)
    record_ranking._sort_records_for_query(merged, query=query, policy_plugin_refs=policy_plugin_refs)
    limit = max(
        1,
        min(
            max(1, int(top_k or 1)),
            (settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_RECORDS or 4),
        ),
    )
    return merged[:limit]


def _metadata_anchor_fallback_candidate_records(
    rows: list[Any] | tuple[Any, ...],
    *,
    scoped_dataset_ids: set[str],
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows or ():
        record = _metadata_anchor_fallback_candidate_record(
            row,
            scoped_dataset_ids=scoped_dataset_ids,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        if record is not None:
            candidates.append(record)
    return candidates


def _metadata_anchor_fallback_candidate_record(
    row: Any,
    *,
    scoped_dataset_ids: set[str],
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    dataset_id = _coerce_uuid_text(_row_value(row, "dataset_id"))
    if dataset_id not in scoped_dataset_ids:
        return None
    content = str(_row_value(row, "content") or "").strip()
    if not content:
        return None
    metadata = _metadata_anchor_row_metadata(row, dataset_id=dataset_id)
    record = {
        "content": answer_hints._content_with_answer_hints(
            content,
            metadata,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        ),
        "score": 0.0,
        "title": str(_row_value(row, "filename") or metadata.get("title") or "metadata-anchor-match").strip(),
        "metadata": metadata,
    }
    score = _metadata_anchor_fallback_record_score(
        record,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    if score <= 0:
        return None
    record["score"] = score
    return record


def _metadata_anchor_row_metadata(row: Any, *, dataset_id: str) -> dict[str, Any]:
    raw_metadata = _row_value(row, "metadata")
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    chunk_id = _coerce_uuid_text(_row_value(row, "chunk_id") or _row_value(row, "id"))
    document_id = _coerce_uuid_text(_row_value(row, "document_id"))
    if chunk_id:
        metadata["chunk_id"] = chunk_id
    if document_id:
        metadata["document_id"] = document_id
    metadata["dataset_id"] = dataset_id
    metadata["dify_metadata_anchor_fallback"] = True
    for key in ("chunk_index", "page_number"):
        value = _row_value(row, key)
        if value is not None:
            metadata[key] = value
    return metadata


def _metadata_anchor_exact_slot_composite(
    candidates: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    if not query_policy._query_has_mixed_intent_for_policy(query, policy_plugin_refs=policy_plugin_refs):
        return None
    requested_slots = query_policy._requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
    if not requested_slots:
        return None
    return record_ranking._composite_record_for_exact_anchor_slots(
        candidates,
        query=query,
        requested_slot_specs=requested_slots,
        policy_plugin_refs=policy_plugin_refs,
    )


class _MetadataAnchorBudgetExceededError(Exception):
    pass


@dataclass
class _MetadataAnchorDBFallbackPlan:
    terms: list[str]
    primary_term: str
    primary_pattern: str
    question_anchor_preferred: bool
    service_anchor_preferred: bool
    query_has_slot_question_intent: bool
    question_anchor_first: bool
    requested_slot_specs: tuple[tuple[str, str], ...]
    service_name_terms: list[str]
    service_anchor_fields: tuple[str, ...]
    mixed_intent_retrieval_queries: tuple[str, ...]


@dataclass
class _MetadataAnchorDBFallbackContext:
    db: Session
    tenant_id: UUID
    scoped_dataset_ids: list[UUID]
    query: str
    top_k: int
    policy_plugin_refs: tuple[str, ...]
    existing_records: list[dict[str, Any]] | None
    max_scan: int
    started: float
    max_elapsed_ms_value: int
    rows: list[Any]
    seen_chunk_ids: set[str]
    statement_timeout_ms: int = 0


def _metadata_anchor_db_fallback_plan(
    query: str,
    *,
    terms: list[str],
    policy_plugin_refs: tuple[str, ...] = (),
    prefer_question_anchor_first: bool,
) -> _MetadataAnchorDBFallbackPlan:
    question_anchor_preferred = query_policy._query_prefers_question_anchor(
        query, policy_plugin_refs=policy_plugin_refs
    )
    service_anchor_preferred = query_policy._query_prefers_service_anchor(query, policy_plugin_refs=policy_plugin_refs)
    query_has_slot_question_intent = bool(
        query_policy._requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
        or _query_intent_terms(
            query,
            intent_terms=query_policy._question_anchor_intent_terms_for_policy_refs(policy_plugin_refs),
        )
    )
    question_anchor_first = query_policy._metadata_anchor_should_query_question_first(
        query,
        query_prefers_question_anchor=question_anchor_preferred,
        query_prefers_service_anchor=service_anchor_preferred,
        prefer_question_anchor_first=bool(prefer_question_anchor_first),
        policy_plugin_refs=policy_plugin_refs,
    )
    requested_slot_specs = query_policy._requested_policy_slot_specs_for_query(
        query, policy_plugin_refs=policy_plugin_refs
    )
    service_name_terms = _metadata_anchor_service_name_query_terms(query, policy_plugin_refs=policy_plugin_refs)
    if not service_name_terms:
        service_name_terms = terms[:_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS]
    return _MetadataAnchorDBFallbackPlan(
        terms=terms,
        primary_term=terms[0],
        primary_pattern=f"%{terms[0].replace('%', '').replace('_', '').strip()}%",
        question_anchor_preferred=question_anchor_preferred,
        service_anchor_preferred=service_anchor_preferred,
        query_has_slot_question_intent=query_has_slot_question_intent,
        question_anchor_first=question_anchor_first,
        requested_slot_specs=requested_slot_specs,
        service_name_terms=service_name_terms,
        service_anchor_fields=query_policy._anchor_binding_fields_for_policy_refs(policy_plugin_refs)
        or ("service_name",),
        mixed_intent_retrieval_queries=query_policy._mixed_intent_retrieval_queries(
            query, policy_plugin_refs=policy_plugin_refs
        ),
    )


def _metadata_anchor_statement_timeout_ms(statement_timeout_ms_override: int | None) -> int:
    configured_statement_timeout = (
        statement_timeout_ms_override
        if statement_timeout_ms_override is not None
        else settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_STATEMENT_TIMEOUT_MS
    )
    return max(0, min(30000, int(configured_statement_timeout or 0)))


def _metadata_anchor_budget_exceeded(ctx: _MetadataAnchorDBFallbackContext) -> bool:
    return bool(ctx.max_elapsed_ms_value) and ((time.perf_counter() - ctx.started) * 1000 >= ctx.max_elapsed_ms_value)


def _metadata_anchor_is_statement_timeout_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "statement timeout" in text or "querycanceled" in text or "canceling statement due to statement timeout" in text
    )


def _metadata_anchor_set_statement_timeout(ctx: _MetadataAnchorDBFallbackContext, timeout_ms: int) -> None:
    ctx.statement_timeout_ms = timeout_ms
    if timeout_ms:
        ctx.db.execute(sql_text(f"SET LOCAL statement_timeout = {timeout_ms}"))


def _metadata_anchor_prepare_statement_timeout(
    ctx: _MetadataAnchorDBFallbackContext,
    *,
    statement_timeout_ms_override: int | None,
) -> None:
    timeout_ms = _metadata_anchor_statement_timeout_ms(statement_timeout_ms_override)
    ctx.statement_timeout_ms = timeout_ms
    if not ctx.max_elapsed_ms_value and timeout_ms:
        _metadata_anchor_set_statement_timeout(ctx, timeout_ms)


def _metadata_anchor_append_unique_rows(
    ctx: _MetadataAnchorDBFallbackContext,
    batch: list[Any] | tuple[Any, ...],
) -> None:
    for row in batch:
        chunk_id = _coerce_uuid_text(_row_value(row, "chunk_id"))
        if not chunk_id or chunk_id in ctx.seen_chunk_ids:
            continue
        ctx.seen_chunk_ids.add(chunk_id)
        ctx.rows.append(row)


def _metadata_anchor_query_matching_rows(
    ctx: _MetadataAnchorDBFallbackContext,
    condition: Any,
    *,
    limit: int,
) -> list[Any]:
    if _metadata_anchor_budget_exceeded(ctx):
        raise _MetadataAnchorBudgetExceededError
    if ctx.max_elapsed_ms_value:
        elapsed_ms = max(0, int((time.perf_counter() - ctx.started) * 1000))
        remaining_ms = max(1, ctx.max_elapsed_ms_value - elapsed_ms)
        timeout_ms = min(ctx.statement_timeout_ms, remaining_ms) if ctx.statement_timeout_ms else remaining_ms
        _metadata_anchor_set_statement_timeout(ctx, timeout_ms)
        if _metadata_anchor_budget_exceeded(ctx):
            raise _MetadataAnchorBudgetExceededError
    return (
        ctx.db.query(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.document_id.label("document_id"),
            DocumentChunk.chunk_index.label("chunk_index"),
            DocumentChunk.page_number.label("page_number"),
            DocumentChunk.content.label("content"),
            DocumentChunk.doc_metadata.label("metadata"),
            Document.dataset_id.label("dataset_id"),
            Document.filename.label("filename"),
        )
        .join(Document, DocumentChunk.document_id == Document.id)
        .filter(
            DocumentChunk.tenant_id == ctx.tenant_id,
            Document.tenant_id == ctx.tenant_id,
            Document.dataset_id.in_(ctx.scoped_dataset_ids),
            Document.status == "completed",
            Document.publication_status == "published",
            Document.archived_at.is_(None),
            DocumentChunk.disabled_at.is_(None),
            Document.disabled_at.is_(None),
            condition,
        )
        .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
        .limit(max(1, int(limit or 1)))
        .all()
    )


def _metadata_anchor_current_matches(ctx: _MetadataAnchorDBFallbackContext) -> list[dict[str, Any]]:
    return _metadata_anchor_fallback_records_from_rows(
        ctx.rows,
        dataset_ids=ctx.scoped_dataset_ids,
        query=ctx.query,
        top_k=ctx.top_k,
        policy_plugin_refs=ctx.policy_plugin_refs,
        existing_records=ctx.existing_records,
    )


def _metadata_anchor_rewind(
    ctx: _MetadataAnchorDBFallbackContext,
    *,
    rows_before: int,
    seen_before: set[str],
) -> None:
    del ctx.rows[rows_before:]
    ctx.seen_chunk_ids.clear()
    ctx.seen_chunk_ids.update(seen_before)


def _metadata_anchor_first_matching_records(
    ctx: _MetadataAnchorDBFallbackContext,
    conditions: list[Any] | tuple[Any, ...],
) -> list[dict[str, Any]] | None:
    for condition in conditions:
        _metadata_anchor_append_unique_rows(
            ctx,
            _metadata_anchor_query_matching_rows(ctx, condition, limit=ctx.max_scan),
        )
        current_matches = _metadata_anchor_current_matches(ctx)
        if current_matches:
            return current_matches
    return None


def _metadata_anchor_exact_service_prefetch_matches(
    ctx: _MetadataAnchorDBFallbackContext,
    plan: _MetadataAnchorDBFallbackPlan,
) -> list[dict[str, Any]] | None:
    should_prefetch = plan.service_anchor_preferred and (
        not (plan.question_anchor_first and plan.query_has_slot_question_intent)
        or len(plan.mixed_intent_retrieval_queries) >= 2
    )
    if not should_prefetch:
        return None
    for service_name_term in plan.service_name_terms:
        exact_service_name = service_name_term.replace("%", "").replace("_", "").strip()
        if not exact_service_name:
            continue
        _metadata_anchor_append_unique_rows(
            ctx,
            _metadata_anchor_query_matching_rows(
                ctx,
                DocumentChunk.doc_metadata["service_name"].astext == exact_service_name,
                limit=ctx.max_scan,
            ),
        )
        current_matches = _metadata_anchor_current_matches(ctx)
        if current_matches:
            return current_matches
    return None


def _metadata_anchor_exact_slot_scan_matches(
    ctx: _MetadataAnchorDBFallbackContext,
    plan: _MetadataAnchorDBFallbackPlan,
) -> list[dict[str, Any]] | None:
    if not (
        query_policy._query_has_mixed_intent_for_policy(ctx.query, policy_plugin_refs=ctx.policy_plugin_refs)
        and plan.requested_slot_specs
        and _query_has_quoted_anchor_candidate(ctx.query)
    ):
        return None
    anchor_conditions = _metadata_anchor_exact_slot_anchor_conditions(
        ctx.query, policy_plugin_refs=ctx.policy_plugin_refs
    )
    slot_conditions = _metadata_anchor_slot_conditions(plan.requested_slot_specs)
    if not anchor_conditions or not slot_conditions:
        return None
    rows_before = len(ctx.rows)
    seen_before = set(ctx.seen_chunk_ids)
    _metadata_anchor_append_unique_rows(
        ctx,
        _metadata_anchor_query_matching_rows(
            ctx,
            and_(or_(*anchor_conditions), or_(*slot_conditions)),
            limit=ctx.max_scan,
        ),
    )
    current_matches = _metadata_anchor_current_matches(ctx)
    if any(_record_is_composite_exact_anchor_answer(record) for record in current_matches):
        return current_matches
    _metadata_anchor_rewind(ctx, rows_before=rows_before, seen_before=seen_before)
    return None


def _metadata_anchor_exact_slot_anchor_conditions(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[Any]:
    anchor_fields = query_policy._anchor_binding_fields_for_policy_refs(policy_plugin_refs) or ("service_name",)
    exact_anchor_terms = list(_quoted_query_anchor_terms(query))
    seen_exact_anchor_terms = {_normalize_match_term(term) for term in exact_anchor_terms}
    for term in query_policy._metadata_anchor_title_query_terms(
        query,
        policy_plugin_refs=policy_plugin_refs,
    )[:_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS]:
        normalized = _normalize_match_term(term)
        if len(normalized) < 4 or normalized in seen_exact_anchor_terms:
            continue
        seen_exact_anchor_terms.add(normalized)
        exact_anchor_terms.append(term)
    conditions: list[Any] = []
    for anchor_term in exact_anchor_terms:
        cleaned_anchor = anchor_term.replace("%", "").replace("_", "").strip()
        if len(_normalize_match_term(cleaned_anchor)) < 4:
            continue
        pattern = f"%{cleaned_anchor}%"
        conditions.extend(DocumentChunk.doc_metadata[field].astext.ilike(pattern) for field in anchor_fields)
    return conditions


def _metadata_anchor_slot_conditions(requested_slot_specs: tuple[tuple[str, str], ...]) -> list[Any]:
    return [
        DocumentChunk.doc_metadata[field].astext == str(slot_value).strip()
        for field, slot_value in requested_slot_specs
        if str(field).strip() and str(slot_value).strip()
    ]


def _metadata_anchor_primary_question_matches(
    ctx: _MetadataAnchorDBFallbackContext,
    plan: _MetadataAnchorDBFallbackPlan,
) -> list[dict[str, Any]] | None:
    if not plan.question_anchor_first:
        return None
    _metadata_anchor_append_unique_rows(
        ctx,
        _metadata_anchor_query_matching_rows(
            ctx,
            DocumentChunk.doc_metadata["question"].astext.ilike(plan.primary_pattern),
            limit=ctx.max_scan,
        ),
    )
    _metadata_anchor_append_unique_rows(
        ctx,
        _metadata_anchor_query_matching_rows(
            ctx,
            or_(
                DocumentChunk.doc_metadata["primary_alias"].astext.ilike(plan.primary_pattern),
                DocumentChunk.doc_metadata["aliases"].astext.ilike(plan.primary_pattern),
                DocumentChunk.doc_metadata.contains({"aliases": [plan.primary_term]}),
            ),
            limit=ctx.max_scan,
        ),
    )
    current_matches = _metadata_anchor_current_matches(ctx)
    if current_matches and not plan.query_has_slot_question_intent:
        return current_matches
    return None


def _metadata_anchor_alias_question_matches(
    ctx: _MetadataAnchorDBFallbackContext,
    plan: _MetadataAnchorDBFallbackPlan,
) -> list[dict[str, Any]] | None:
    if not (plan.question_anchor_first and plan.query_has_slot_question_intent):
        return None
    alias_scan_conditions = _metadata_anchor_alias_scan_conditions(ctx.query, policy_plugin_refs=ctx.policy_plugin_refs)
    if not alias_scan_conditions:
        return None
    rows_before = len(ctx.rows)
    _metadata_anchor_append_unique_rows(
        ctx,
        _metadata_anchor_query_matching_rows(ctx, or_(*alias_scan_conditions), limit=ctx.max_scan),
    )
    if len(ctx.rows) == rows_before:
        return None
    return _metadata_anchor_current_matches(ctx)


def _metadata_anchor_alias_scan_conditions(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[Any]:
    conditions: list[Any] = []
    for alias_term in query_policy._metadata_anchor_title_query_terms(
        query,
        policy_plugin_refs=policy_plugin_refs,
    )[:_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS]:
        cleaned_alias_term = alias_term.replace("%", "").replace("_", "").strip()
        if not cleaned_alias_term:
            continue
        pattern = f"%{cleaned_alias_term}%"
        conditions.append(
            or_(
                DocumentChunk.doc_metadata["question"].astext.ilike(pattern),
                DocumentChunk.doc_metadata["primary_alias"].astext.ilike(pattern),
                DocumentChunk.doc_metadata["aliases"].astext.ilike(pattern),
                DocumentChunk.doc_metadata.contains({"aliases": [alias_term]}),
            )
        )
    return conditions


def _metadata_anchor_question_conditions(terms: list[str]) -> list[Any]:
    conditions: list[Any] = []
    for term in terms[1:]:
        cleaned_term = term.replace("%", "").replace("_", "").strip()
        if not cleaned_term:
            continue
        pattern = f"%{cleaned_term}%"
        conditions.append(
            or_(
                DocumentChunk.doc_metadata["question"].astext.ilike(pattern),
                DocumentChunk.doc_metadata["primary_alias"].astext.ilike(pattern),
            )
        )
    return conditions


def _metadata_anchor_secondary_question_matches(
    ctx: _MetadataAnchorDBFallbackContext,
    plan: _MetadataAnchorDBFallbackPlan,
) -> list[dict[str, Any]] | None:
    if not plan.question_anchor_first:
        return None
    question_conditions = _metadata_anchor_question_conditions(plan.terms)
    if not question_conditions:
        return None
    _metadata_anchor_append_unique_rows(
        ctx,
        _metadata_anchor_query_matching_rows(ctx, or_(*question_conditions), limit=ctx.max_scan),
    )
    return _metadata_anchor_current_matches(ctx)


def _metadata_anchor_exact_question_matches(
    ctx: _MetadataAnchorDBFallbackContext,
    plan: _MetadataAnchorDBFallbackPlan,
) -> list[dict[str, Any]] | None:
    if not (
        query_policy._query_has_mixed_intent_for_policy(ctx.query, policy_plugin_refs=ctx.policy_plugin_refs)
        and _query_has_quoted_anchor_candidate(ctx.query)
        and plan.question_anchor_preferred
    ):
        return None
    exact_question_conditions = _metadata_anchor_exact_question_conditions(ctx.query, terms=plan.terms)
    if not exact_question_conditions:
        return None
    rows_before = len(ctx.rows)
    seen_before = set(ctx.seen_chunk_ids)
    _metadata_anchor_append_unique_rows(
        ctx,
        _metadata_anchor_query_matching_rows(ctx, or_(*exact_question_conditions), limit=ctx.max_scan),
    )
    current_matches = _metadata_anchor_current_matches(ctx)
    if record_processing._compact_mixed_intent_exact_anchor_records(
        current_matches,
        query=ctx.query,
        top_k=ctx.top_k,
        policy_plugin_refs=ctx.policy_plugin_refs,
    ):
        return current_matches
    _metadata_anchor_rewind(ctx, rows_before=rows_before, seen_before=seen_before)
    return None


def _metadata_anchor_exact_question_conditions(query: str, *, terms: list[str]) -> list[Any]:
    quoted_anchor_norms = tuple(_quoted_query_anchor_terms(query))
    exact_question_terms = list(quoted_anchor_norms)
    seen_exact_question_terms = set(exact_question_terms)
    for term in terms:
        normalized_term = _normalize_match_term(term)
        if (
            len(normalized_term) >= 4
            and normalized_term not in seen_exact_question_terms
            and any(normalized_term in anchor or anchor in normalized_term for anchor in quoted_anchor_norms)
        ):
            seen_exact_question_terms.add(normalized_term)
            exact_question_terms.append(term)
    return [
        DocumentChunk.doc_metadata["question"].astext.ilike(
            f"%{anchor_term.replace('%', '').replace('_', '').strip()}%"
        )
        for anchor_term in exact_question_terms
        if anchor_term.replace("%", "").replace("_", "").strip()
    ]


def _metadata_anchor_quoted_slot_matches(
    ctx: _MetadataAnchorDBFallbackContext,
    plan: _MetadataAnchorDBFallbackPlan,
) -> list[dict[str, Any]] | None:
    if not (
        query_policy._query_has_mixed_intent_for_policy(ctx.query, policy_plugin_refs=ctx.policy_plugin_refs)
        and _query_has_quoted_anchor_candidate(ctx.query)
        and plan.requested_slot_specs
    ):
        return None
    anchor_conditions = _metadata_anchor_quoted_anchor_conditions(
        ctx.query,
        plan.service_anchor_fields,
    )
    slot_conditions = _metadata_anchor_slot_conditions(plan.requested_slot_specs)
    if not anchor_conditions or not slot_conditions:
        return None
    _metadata_anchor_append_unique_rows(
        ctx,
        _metadata_anchor_query_matching_rows(
            ctx,
            and_(or_(*anchor_conditions), or_(*slot_conditions)),
            limit=ctx.max_scan,
        ),
    )
    current_matches = _metadata_anchor_current_matches(ctx)
    if record_processing._compact_mixed_intent_exact_anchor_records(
        current_matches,
        query=ctx.query,
        top_k=ctx.top_k,
        policy_plugin_refs=ctx.policy_plugin_refs,
    ):
        return current_matches
    return None


def _metadata_anchor_quoted_anchor_conditions(query: str, anchor_fields: tuple[str, ...]) -> list[Any]:
    conditions: list[Any] = []
    if not anchor_fields:
        return conditions
    for anchor_term in _quoted_query_anchor_terms(query):
        cleaned_anchor = anchor_term.replace("%", "").replace("_", "").strip()
        if len(_normalize_match_term(cleaned_anchor)) < 4:
            continue
        pattern = f"%{cleaned_anchor}%"
        conditions.extend(DocumentChunk.doc_metadata[field].astext.ilike(pattern) for field in anchor_fields)
    return conditions


def _metadata_anchor_exact_service_name_conditions(plan: _MetadataAnchorDBFallbackPlan) -> list[Any]:
    return [
        DocumentChunk.doc_metadata[field].astext == term.replace("%", "").replace("_", "").strip()
        for term in plan.service_name_terms[:_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS]
        for field in plan.service_anchor_fields
        if term.replace("%", "").replace("_", "").strip()
    ]


def _metadata_anchor_service_name_conditions(plan: _MetadataAnchorDBFallbackPlan) -> list[Any]:
    return [
        DocumentChunk.doc_metadata[field].astext.ilike(f"%{term.replace('%', '').replace('_', '').strip()}%")
        for term in plan.service_name_terms
        for field in plan.service_anchor_fields
        if term.replace("%", "").replace("_", "").strip()
    ]


def _metadata_anchor_title_conditions(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[Any]:
    conditions: list[Any] = []
    for title_term in query_policy._metadata_anchor_title_query_terms(query, policy_plugin_refs=policy_plugin_refs):
        cleaned_term = title_term.replace("%", "").replace("_", "").strip()
        if not cleaned_term:
            continue
        pattern = f"%{cleaned_term}%"
        conditions.append(
            or_(
                *[
                    DocumentChunk.doc_metadata[field].astext.ilike(pattern)
                    for field in _METADATA_ANCHOR_DB_FALLBACK_TITLE_FIELDS
                ]
            )
        )
    return conditions


def _metadata_anchor_service_name_near_conditions(plan: _MetadataAnchorDBFallbackPlan) -> list[Any]:
    conditions: list[Any] = []
    for term in plan.service_name_terms:
        normalized = _normalize_match_term(term)
        if len(normalized) < 4 or not _CJK_RE.search(normalized):
            continue
        left = normalized[:2]
        right = normalized[-2:]
        if left == right:
            continue
        for field in plan.service_anchor_fields:
            conditions.append(
                and_(
                    DocumentChunk.doc_metadata[field].astext.ilike(f"%{left}%"),
                    DocumentChunk.doc_metadata[field].astext.ilike(f"%{right}%"),
                )
            )
    return conditions


def _metadata_anchor_service_and_title_matches(
    ctx: _MetadataAnchorDBFallbackContext,
    plan: _MetadataAnchorDBFallbackPlan,
) -> list[dict[str, Any]] | None:
    for conditions in (
        _metadata_anchor_exact_service_name_conditions(plan),
        _metadata_anchor_service_name_conditions(plan),
        _metadata_anchor_title_conditions(ctx.query, policy_plugin_refs=ctx.policy_plugin_refs),
        _metadata_anchor_service_name_near_conditions(plan),
    ):
        matches = _metadata_anchor_first_matching_records(
            ctx,
            list(conditions) if isinstance(conditions, tuple) else conditions,
        )
        if matches:
            return matches
    return None


def _metadata_anchor_intent_field_matches(
    ctx: _MetadataAnchorDBFallbackContext,
    *,
    primary_term: str,
) -> list[dict[str, Any]] | None:
    for field in ("retrieval_intents", "query_intents", "intent_terms"):
        _metadata_anchor_append_unique_rows(
            ctx,
            _metadata_anchor_query_matching_rows(
                ctx,
                DocumentChunk.doc_metadata.contains({field: [primary_term]}),
                limit=ctx.max_scan,
            ),
        )
        current_matches = _metadata_anchor_current_matches(ctx)
        if current_matches:
            return current_matches
    return None


def _metadata_anchor_term_scan_matches(
    ctx: _MetadataAnchorDBFallbackContext,
    *,
    terms: list[str],
) -> list[dict[str, Any]] | None:
    for term in terms:
        cleaned_term = term.replace("%", "").replace("_", "").strip()
        if not cleaned_term:
            continue
        pattern = f"%{cleaned_term}%"
        field_conditions: list[Any] = [DocumentChunk.doc_metadata["question"].astext.ilike(pattern)]
        field_conditions.append(
            or_(
                *[
                    DocumentChunk.doc_metadata[field].astext.ilike(pattern)
                    for field in _METADATA_ANCHOR_DB_FALLBACK_SCALAR_FIELDS
                    if field != "question"
                ]
            )
        )
        matches = _metadata_anchor_first_matching_records(ctx, field_conditions)
        if matches:
            return matches
        matches = _metadata_anchor_intent_field_matches(ctx, primary_term=cleaned_term)
        if matches:
            return matches
        for field in _METADATA_ANCHOR_DB_FALLBACK_ARRAY_FIELDS:
            if field in {"retrieval_intents", "query_intents", "intent_terms"}:
                continue
            _metadata_anchor_append_unique_rows(
                ctx,
                _metadata_anchor_query_matching_rows(
                    ctx,
                    DocumentChunk.doc_metadata.contains({field: [cleaned_term]}),
                    limit=ctx.max_scan,
                ),
            )
            current_matches = _metadata_anchor_current_matches(ctx)
            if current_matches:
                return current_matches
        if len(ctx.rows) >= ctx.max_scan:
            break
    return None


def _metadata_anchor_text_scan_matches(
    ctx: _MetadataAnchorDBFallbackContext,
    *,
    terms: list[str],
) -> list[dict[str, Any]] | None:
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_TEXT_SCAN_ENABLED:
        return None
    metadata_text = sql_cast(DocumentChunk.doc_metadata, SQLText)
    for term in terms[:3]:
        cleaned_term = term.replace("%", "").replace("_", "").strip()
        if not cleaned_term:
            continue
        _metadata_anchor_append_unique_rows(
            ctx,
            _metadata_anchor_query_matching_rows(
                ctx,
                metadata_text.ilike(f"%{cleaned_term}%"),
                limit=ctx.max_scan,
            ),
        )
        current_matches = _metadata_anchor_current_matches(ctx)
        if current_matches:
            return current_matches
    return None


def _metadata_anchor_db_fallback_scan_matches(
    ctx: _MetadataAnchorDBFallbackContext,
    plan: _MetadataAnchorDBFallbackPlan,
) -> list[dict[str, Any]] | None:
    for finder in (
        _metadata_anchor_exact_service_prefetch_matches,
        _metadata_anchor_exact_slot_scan_matches,
        _metadata_anchor_primary_question_matches,
        _metadata_anchor_alias_question_matches,
        _metadata_anchor_secondary_question_matches,
        _metadata_anchor_exact_question_matches,
        _metadata_anchor_quoted_slot_matches,
    ):
        matches = finder(ctx, plan)
        if matches:
            return matches
    if plan.question_anchor_preferred and not plan.service_anchor_preferred:
        return []
    matches = _metadata_anchor_service_and_title_matches(ctx, plan)
    if matches:
        return matches
    matches = _metadata_anchor_intent_field_matches(ctx, primary_term=plan.primary_term)
    if matches:
        return matches
    matches = _metadata_anchor_term_scan_matches(ctx, terms=plan.terms)
    if matches:
        return matches
    return _metadata_anchor_text_scan_matches(ctx, terms=plan.terms)


def _prepare_metadata_anchor_db_fallback(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_ids: list[UUID],
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
    existing_records: list[dict[str, Any]] | None = None,
    metadata_filter: dict[str, Any] | None = None,
    prefer_question_anchor_first: bool = False,
    max_elapsed_ms: int | None = None,
) -> tuple[_MetadataAnchorDBFallbackContext, _MetadataAnchorDBFallbackPlan] | None:
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED:
        return None
    if metadata_filter:
        return None
    if record_ranking._records_can_skip_metadata_anchor_fallback(
        existing_records or [],
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return None
    scoped_dataset_ids = common._dedupe_dataset_ids(list(dataset_ids or []))
    if not scoped_dataset_ids:
        return None
    terms = _metadata_anchor_fallback_query_terms(query)
    if not terms:
        return None
    max_scan = max(
        1,
        min(
            500,
            (settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_SCAN or 80),
        ),
    )
    started = time.perf_counter()
    ctx = _MetadataAnchorDBFallbackContext(
        db=db,
        tenant_id=tenant_id,
        scoped_dataset_ids=scoped_dataset_ids,
        query=query,
        top_k=top_k,
        policy_plugin_refs=policy_plugin_refs,
        existing_records=existing_records,
        max_scan=max_scan,
        started=started,
        max_elapsed_ms_value=max(0, min(30000, int(max_elapsed_ms or 0))),
        rows=[],
        seen_chunk_ids=set(),
    )
    plan = _metadata_anchor_db_fallback_plan(
        query,
        terms=terms,
        policy_plugin_refs=policy_plugin_refs,
        prefer_question_anchor_first=prefer_question_anchor_first,
    )
    return ctx, plan


def _metadata_anchor_db_fallback_result(
    ctx: _MetadataAnchorDBFallbackContext,
    plan: _MetadataAnchorDBFallbackPlan,
    *,
    statement_timeout_ms_override: int | None,
) -> list[dict[str, Any]]:
    try:
        _metadata_anchor_prepare_statement_timeout(
            ctx,
            statement_timeout_ms_override=statement_timeout_ms_override,
        )
        matches = _metadata_anchor_db_fallback_scan_matches(ctx, plan)
        if matches is not None:
            return matches
    except _MetadataAnchorBudgetExceededError:
        logger.info(
            "Dify metadata anchor fallback budget exhausted query_hash=%s elapsed_ms=%s max_elapsed_ms=%s rows=%s",
            _diagnostic_query_hash(ctx.query),
            round((time.perf_counter() - ctx.started) * 1000, 2),
            ctx.max_elapsed_ms_value,
            len(ctx.rows),
            extra={
                "event": "dify_metadata_anchor_budget_exhausted",
                "query_hash": _diagnostic_query_hash(ctx.query),
                "elapsed_ms": round((time.perf_counter() - ctx.started) * 1000, 2),
                "max_elapsed_ms": ctx.max_elapsed_ms_value,
            },
        )
    except Exception as exc:  # noqa: BLE001
        try:
            ctx.db.rollback()
        except Exception:  # noqa: BLE001
            logger.debug("Failed to rollback Dify metadata anchor fallback transaction", exc_info=True)
        if _metadata_anchor_is_statement_timeout_error(exc):
            logger.info(
                "Dify metadata anchor fallback budget exhausted query_hash=%s elapsed_ms=%s "
                "statement_timeout_ms=%s rows=%s",
                _diagnostic_query_hash(ctx.query),
                round((time.perf_counter() - ctx.started) * 1000, 2),
                ctx.statement_timeout_ms,
                len(ctx.rows),
                extra={
                    "event": "dify_metadata_anchor_budget_exhausted",
                    "query_hash": _diagnostic_query_hash(ctx.query),
                    "elapsed_ms": round((time.perf_counter() - ctx.started) * 1000, 2),
                    "statement_timeout_ms": ctx.statement_timeout_ms,
                    "row_count": len(ctx.rows),
                },
            )
        else:
            logger.warning("Failed to run Dify metadata anchor fallback", exc_info=True)
            return []
    finally:
        if ctx.max_elapsed_ms_value:
            try:
                ctx.db.rollback()
            except Exception:  # noqa: BLE001
                logger.debug("Failed to reset Dify metadata anchor fallback transaction", exc_info=True)
    return _metadata_anchor_fallback_records_from_rows(
        ctx.rows,
        dataset_ids=ctx.scoped_dataset_ids,
        query=ctx.query,
        top_k=ctx.top_k,
        policy_plugin_refs=ctx.policy_plugin_refs,
        existing_records=ctx.existing_records,
    )


def find_anchor_records(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_ids: list[UUID],
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
    existing_records: list[dict[str, Any]] | None = None,
    metadata_filter: dict[str, Any] | None = None,
    prefer_question_anchor_first: bool = False,
    statement_timeout_ms_override: int | None = None,
    max_elapsed_ms: int | None = None,
) -> list[dict[str, Any]]:
    prepared = _prepare_metadata_anchor_db_fallback(
        db=db,
        tenant_id=tenant_id,
        dataset_ids=dataset_ids,
        query=query,
        top_k=top_k,
        policy_plugin_refs=policy_plugin_refs,
        existing_records=existing_records,
        metadata_filter=metadata_filter,
        prefer_question_anchor_first=prefer_question_anchor_first,
        max_elapsed_ms=max_elapsed_ms,
    )
    if prepared is None:
        return []
    ctx, plan = prepared
    return _metadata_anchor_db_fallback_result(
        ctx,
        plan,
        statement_timeout_ms_override=statement_timeout_ms_override,
    )


def _find_anchor_records_with_managed_session(
    *,
    budget_deadline: float | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    if budget_deadline is not None:
        remaining_ms = max(0, int((budget_deadline - time.perf_counter()) * 1000))
        if remaining_ms <= 0:
            return []
        configured_budget = int(kwargs.get("max_elapsed_ms") or 0)
        kwargs["max_elapsed_ms"] = min(remaining_ms, configured_budget) if configured_budget > 0 else remaining_ms
    worker_db = SessionLocal()
    try:
        return find_anchor_records(db=worker_db, **kwargs)
    finally:
        worker_db.close()


async def run_with_deadline(
    call_kwargs: dict[str, Any],
    *,
    budget_deadline: float | None,
) -> list[dict[str, Any]]:
    if budget_deadline is None:
        return await run_blocking_retrieval_call(
            _find_anchor_records_with_managed_session,
            budget_deadline=None,
            **call_kwargs,
        )
    remaining_sec = budget_deadline - time.perf_counter()
    if remaining_sec <= 0:
        return []
    try:
        return await asyncio.wait_for(
            run_blocking_retrieval_call(
                _find_anchor_records_with_managed_session,
                budget_deadline=budget_deadline,
                **call_kwargs,
            ),
            timeout=remaining_sec,
        )
    except TimeoutError:
        logger.info(
            "Dify metadata anchor fallback exceeded request budget query_hash=%s",
            _diagnostic_query_hash(str(call_kwargs.get("query") or "")),
        )
        return []
