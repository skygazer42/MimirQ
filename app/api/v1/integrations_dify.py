"""
Dify external knowledge adapter.

This router exposes Ragvia datasets as a Dify External Knowledge API source.
Dify calls this endpoint with a `knowledge_id`; Ragvia maps it to one or more
dataset IDs, runs the existing retrieval-only pipeline, and returns Dify records.
"""

import asyncio
import contextlib
import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import Text as SQLText
from sqlalchemy import and_, or_
from sqlalchemy import cast as sql_cast
from sqlalchemy.orm import Session

from app.api.schemas.conversations import ChatRAGConfig
from app.api.schemas.integrations import (
    DifyConversationTurnRequest,
    DifyConversationTurnResponse,
    DifyExternalKnowledgeRecord,
    DifyExternalKnowledgeRequest,
    DifyExternalKnowledgeResponse,
    DifyRetrievalSetting,
)
from app.api.v1.dify_support.external_api import (
    _dify_trace_conversation_id,
    _persist_dify_conversation_turn,
    _request_client_ip,
    _require_dify_actor,
)
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.models.dataset import Dataset
from app.models.document import DocumentChunk
from app.rag.core.logging import get_logger
from app.rag.reranker.factory import get_reranker
from app.rag.retrieval.planner import (
    DatasetScopePlan,
)
from app.rag.retrieval.plugin_policy import (
    filter_records_by_retrieval_policy_alignment,
    record_retrieval_policy_anchor_binding_scores,
    record_retrieval_policy_bonus,
)
from app.services.chat_response_cache import (
    InflightResponseLeaderCancelledError,
    get_best_effort_json_cache_value,
    try_acquire_best_effort_redis_lease,
)
from app.services.chat_response_cache import acquire_inflight_chat_response as acquire_inflight_response
from app.services.chat_response_cache import reject_inflight_chat_response as reject_inflight_response
from app.services.chat_response_cache import resolve_inflight_chat_response as resolve_inflight_response
from app.services.dify_integration.anchor_strength import (
    _dify_kg_float,
    _dify_kg_int,
    _query_intent_terms,
    _record_has_any_requested_slot_field,
    _record_is_composite_exact_anchor_answer,
)
from app.services.dify_integration.answer_hints import (
    _content_with_answer_hints,
)
from app.services.dify_integration.chunk_hydration import (
    _load_chunk_content_map_with_managed_session,
)
from app.services.dify_integration.citation_records import (
    _citation_to_dify_record,
    _records_from_citations_with_managed_hydration,
)
from app.services.dify_integration.common import (
    _ANCHOR_ONLY_QA_RECORD_PENALTY,
    _ANSWERFUL_RECORD_BONUS,
    _METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS,
    _MIXED_INTENT_SPLIT_RE,
    _QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH,
    _clamp_score,
    _dedupe_dataset_ids,
    _first_nonempty_str,
    _iter_record_metadata_layers,
    _normalize_match_term,
    _uuid_or_none,
)
from app.services.dify_integration.compaction import (
    _dify_fast_candidate_top_k,
    _dify_fast_response_top_k,
    _record_url_evidence_bonus,
)
from app.services.dify_integration.conversation_turns import (
    _dify_turn_source_conversation_id,
    _dify_turn_source_message_id,
    _dify_turn_source_run_id,
)
from app.services.dify_integration.kg_on_demand import (
    _dify_kg_chunk_events,
    _dify_kg_on_demand_dataset_ids,
    _dify_kg_on_demand_max_records,
    _dify_kg_record_citation,
    _load_dify_kg_chunk_rows_with_managed_session,
)
from app.services.dify_integration.knowledge_scope import (
    extend_sibling_policy_scope as _metadata_anchor_dataset_ids_for_query,
)
from app.services.dify_integration.knowledge_scope import load_knowledge_map as _load_knowledge_map
from app.services.dify_integration.knowledge_scope import (
    resolve_policy_fallback_multiplier as _resolve_knowledge_policy_fallback_multiplier,
)
from app.services.dify_integration.knowledge_scope import (
    resolve_policy_filter_fields as _resolve_knowledge_policy_filter_fields,
)
from app.services.dify_integration.knowledge_scope import (
    resolve_policy_plugin_refs as _resolve_knowledge_policy_plugin_refs,
)
from app.services.dify_integration.knowledge_scope import resolve_scope as _resolve_knowledge_dataset_scope
from app.services.dify_integration.knowledge_scope import (
    resolve_warmup_knowledge_ids as _resolve_dify_warmup_knowledge_ids,
)
from app.services.dify_integration.metadata_anchor import (
    _metadata_anchor_alias_scan_conditions,
    _metadata_anchor_append_unique_rows,
    _metadata_anchor_exact_question_conditions,
    _metadata_anchor_exact_service_name_conditions,
    _metadata_anchor_exact_slot_anchor_conditions,
    _metadata_anchor_fallback_query_terms,
    _metadata_anchor_is_statement_timeout_error,
    _metadata_anchor_prepare_statement_timeout,
    _metadata_anchor_query_matching_rows,
    _metadata_anchor_question_conditions,
    _metadata_anchor_quoted_anchor_conditions,
    _metadata_anchor_rewind,
    _metadata_anchor_row_metadata,
    _metadata_anchor_service_name_conditions,
    _metadata_anchor_service_name_near_conditions,
    _metadata_anchor_slot_conditions,
    _metadata_anchor_title_conditions,
    _MetadataAnchorBudgetExceededError,
    _MetadataAnchorDBFallbackContext,
    _MetadataAnchorDBFallbackPlan,
    _query_has_specific_fast_metadata_anchor_candidate,
)
from app.services.dify_integration.metadata_condition_helpers import (
    MetadataConditionValidationError as _MetadataConditionValidationError,
)
from app.services.dify_integration.metadata_condition_helpers import (
    dify_metadata_condition_item_to_filter as _service_dify_metadata_condition_item_to_filter,
)
from app.services.dify_integration.metadata_condition_helpers import (
    metadata_condition_to_filter as _service_metadata_condition_to_filter,
)
from app.services.dify_integration.policy_helpers import (
    apply_policy_fallback_candidate_multiplier as _service_apply_policy_fallback_candidate_multiplier,
)
from app.services.dify_integration.policy_helpers import (
    knowledge_mapping_plugin_refs as _service_knowledge_mapping_plugin_refs,
)
from app.services.dify_integration.policy_helpers import response_hints_for_record as _response_hints_for_record
from app.services.dify_integration.policy_helpers import (
    retrieval_policy_for_plugin_ref as _retrieval_policy_for_plugin_ref,
)
from app.services.dify_integration.query_policy import (
    _anchor_binding_fields_for_policy_refs,
    _append_mixed_intent_queries_for_segment_parts,
    _append_unique_mixed_intent_query,
    _metadata_anchor_should_query_question_first,
    _mixed_intent_policy_slot_queries_from_inferred_subject,
    _query_blocks_metadata_anchor_preflight,
    _query_has_mixed_intent_for_policy,
    _query_prefers_question_anchor,
    _query_prefers_service_anchor,
    _question_anchor_intent_terms_for_policy_refs,
    _requested_policy_slot_specs_for_query,
)
from app.services.dify_integration.query_terms import (
    _metadata_anchor_service_name_query_terms,
)
from app.services.dify_integration.record_helpers import (
    compact_mixed_intent_exact_anchor_records as _service_compact_mixed_intent_exact_anchor_records,
)
from app.services.dify_integration.record_helpers import (
    compact_records_for_response as _service_compact_records_for_response,
)
from app.services.dify_integration.record_helpers import dedupe_records as _service_dedupe_records
from app.services.dify_integration.record_processing import (
    _compact_by_strong_question_anchor,
    _compact_fast_records_for_response,
    _compact_high_confidence_for_response,
    _response_compaction_for_records,
)
from app.services.dify_integration.record_ranking import (
    _best_exact_anchor_slot_group_records,
    _composite_exact_anchor_slot_content,
    _exact_anchor_slot_record_groups,
    _filter_records_by_mixed_intent_subject_anchor,
    _final_rerank_candidates,
    _ordered_final_rerank_records,
    _record_content_is_answerful,
    _record_covers_requested_policy_slots,
    _record_exact_anchor_protection_scores,
    _record_exact_query_anchor_terms,
    _record_has_answer_evidence,
    _record_has_strong_question_anchor,
    _record_intent_bonus,
    _record_matches_quoted_query_anchor_for_policy,
    _record_question_anchor_strength,
    _record_question_intent_bonus,
    _records_can_skip_metadata_anchor_fallback,
    _records_have_confident_metadata_anchor,
    _records_have_exact_anchor_full_answer,
    _records_have_strong_question_anchor,
    _records_retrieval_policy_diagnostics,
    _strong_question_anchor_records,
)
from app.services.dify_integration.records import (
    _coerce_uuid_text,
    _record_dedupe_key,
    _row_value,
    _tag_mixed_intent_records,
)
from app.services.dify_integration.request_preferences import (
    _disabled_dify_kg_flags,
    _resolve_dify_kg_flags,
    _resolve_dify_latency_profile,
    _resolve_internal_candidate_top_k,
    _resolve_mixed_intent_subquery_top_k,
)
from app.services.dify_integration.response_cache import (
    _acquire_dify_warmup_lease,
    _cleanup_distributed_dify_response_lease,
    _dify_singleflight_lease_ttl_sec,
    _dify_singleflight_result_key,
    _DifyDistributedLease,
    _DifyResponseCache,
    _maintain_best_effort_dify_lease,
    _release_distributed_dify_response_lease,
    _set_dify_response_cache_redis_payload,
)
from app.services.dify_integration.scoring import (
    _diagnostic_query_hash,
    _diagnostic_value_hash,
    _dify_external_reranker_enabled,
    _query_has_quoted_anchor_candidate,
    _quoted_query_anchor_display_terms,
    _record_exact_primary_alias_bonus,
    _record_metadata_anchor_bonus,
    _record_needs_final_rerank,
    _record_plugin_ref,
    _response_hint_string_list,
)
from app.services.dify_integration.tracing import _dify_trace_request_id, _log_dify_external_rag_trace
from app.services.dify_integration.warmup_state import (
    set_dify_external_warmup_status as _set_dify_external_warmup_status,
)
from app.services.document_access import get_allowed_document_id_sets, get_readable_datasets_map
from app.services.rag_runtime_limiter import (
    RetrievalAdmissionTimeoutError,
    run_blocking_call_with_managed_session,
    run_blocking_retrieval_call,
)
from app.types.dify_integration import DifyActor as _DifyActor
from app.types.dify_integration import DifyKGFlags as _DifyKGFlags

logger = get_logger(__name__)

__all__ = [
    "persist_dify_conversation_turn",
    "retrieve_external_knowledge",
    "router",
    "start_dify_external_knowledge_warmup",
]

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    401: {"description": "Unauthorized"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    503: {"description": "Service Unavailable"},
}

_TOKEN_SPLIT_RE = re.compile(r"[,\s]+")
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
_DIFY_WARMUP_DEFAULT_QUERY = "warmup probe"
_DIFY_TRACE_QUERY_PREVIEW_MAX_CHARS = 160
_DIFY_TRACE_QUERY_PATH_MAX_CHARS = 120


class _DifyErrorRoute(APIRoute):
    def get_route_handler(self):  # noqa: ANN201
        original_route_handler = super().get_route_handler()

        async def _custom_route_handler(request: Request):  # noqa: ANN202
            try:
                return await original_route_handler(request)
            except HTTPException as exc:
                return _dify_error_response(exc)

        return _custom_route_handler


def _dify_error_response(exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "error_code" in detail and "error_msg" in detail:
        payload = {"error_code": int(detail["error_code"]), "error_msg": str(detail["error_msg"])}
    else:
        msg = str(detail)
        if exc.status_code == 401 and "authorization header" in msg.lower():
            code = 1001
        elif exc.status_code == 401:
            code = 1002
        elif exc.status_code == 404 and "knowledge" in msg.lower():
            code = 2001
        else:
            code = int(exc.status_code or 500)
        payload = {"error_code": code, "error_msg": msg or "Dify external knowledge request failed"}
    return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)


router = APIRouter(route_class=_DifyErrorRoute, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


_dify_response_cache = _DifyResponseCache()
_DIFY_RESPONSE_CACHE_REDIS_SCHEMA = "mimirq.dify_external_response_cache.redis.v1"
_DIFY_RESPONSE_SINGLEFLIGHT_LEASE_SUFFIX = ":lease"
_DIFY_RESPONSE_SINGLEFLIGHT_RESULT_SUFFIX = ":transient_result"
_DIFY_RESPONSE_SINGLEFLIGHT_RESULT_TTL_SEC = 10
_DIFY_RESPONSE_SINGLEFLIGHT_LEASE_POLL_INITIAL_SEC = 0.05
_DIFY_RESPONSE_SINGLEFLIGHT_LEASE_POLL_MAX_SEC = 0.25
_DIFY_WARMUP_LEASE_KEY = "dify:warmup:lease"
_dify_external_warmup_tasks: set[asyncio.Task[Any]] = set()


def _dify_singleflight_wait_timeout_sec() -> float:
    return max(
        1e-3,
        float(settings.DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC),
    )


def _clear_dify_response_cache() -> None:
    _dify_response_cache.clear()


async def _acquire_or_wait_for_inflight_response(
    key: str,
) -> tuple[bool, dict[str, Any] | None, asyncio.Future[dict[str, Any]]]:
    loop = asyncio.get_running_loop()
    wait_timeout_sec = _dify_singleflight_wait_timeout_sec()
    deadline = loop.time() + wait_timeout_sec
    while True:
        leader, future = await acquire_inflight_response(key)
        if leader:
            return True, None, future
        try:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise RetrievalAdmissionTimeoutError(wait_timeout_sec)
            done, _pending = await asyncio.wait(
                {future},
                timeout=max(1e-3, remaining),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise RetrievalAdmissionTimeoutError(wait_timeout_sec)
            return False, future.result(), future
        except InflightResponseLeaderCancelledError:
            continue


async def _dify_response_cache_redis_payload(key: str) -> list[dict[str, Any]] | None:
    payload = await get_best_effort_json_cache_value(key)
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return None
    return [dict(record) for record in records if isinstance(record, dict)]


async def _dify_distributed_singleflight_payload(
    key: str,
    *,
    response_cache_enabled: bool,
) -> list[dict[str, Any]] | None:
    if response_cache_enabled:
        cached = await _dify_response_cache_redis_payload(key)
        if cached is not None:
            return cached
    return await _dify_response_cache_redis_payload(_dify_singleflight_result_key(key))


async def _acquire_or_wait_for_distributed_dify_response(
    key: str,
    *,
    response_cache_enabled: bool,
    response_cache_ttl_sec: int,
) -> tuple[bool, list[dict[str, Any]] | None, _DifyDistributedLease | None]:
    if not key:
        return True, None, None

    lease_key = f"{key}{_DIFY_RESPONSE_SINGLEFLIGHT_LEASE_SUFFIX}"
    owner = uuid.uuid4().hex
    lease_ttl_sec = _dify_singleflight_lease_ttl_sec(response_cache_ttl_sec)
    poll_delay = _DIFY_RESPONSE_SINGLEFLIGHT_LEASE_POLL_INITIAL_SEC
    wait_timeout_sec = _dify_singleflight_wait_timeout_sec()
    deadline = time.monotonic() + wait_timeout_sec

    while True:
        cached = await _dify_distributed_singleflight_payload(
            key,
            response_cache_enabled=response_cache_enabled,
        )
        if cached is not None:
            return False, cached, None

        acquired = await try_acquire_best_effort_redis_lease(
            lease_key,
            value=owner,
            ttl_sec=lease_ttl_sec,
        )
        if acquired is None:
            return True, None, None
        if acquired:
            return True, None, _DifyDistributedLease(lease_key=lease_key, owner=owner)

        if time.monotonic() >= deadline:
            logger.warning(
                "Dify distributed singleflight timed out waiting for lease payload: %s (timeout=%.2fs)",
                key,
                wait_timeout_sec,
            )
            raise RetrievalAdmissionTimeoutError(wait_timeout_sec)

        await asyncio.sleep(poll_delay)
        poll_delay = min(_DIFY_RESPONSE_SINGLEFLIGHT_LEASE_POLL_MAX_SEC, poll_delay * 1.5)


def _dify_warmup_can_use_retrieval_slot() -> bool:
    try:
        limit = int(settings.RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY)
    except (TypeError, ValueError):
        limit = 1
    return limit <= 0 or limit > 1


def _resolve_dify_response_cache_corpus_token(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_ids: list[UUID],
) -> str | None:
    scoped_dataset_ids = _dedupe_dataset_ids(dataset_ids)
    if not scoped_dataset_ids:
        return None
    try:
        rows = (
            db.query(Dataset.id, Dataset.updated_at)
            .filter(Dataset.tenant_id == tenant_id, Dataset.id.in_(scoped_dataset_ids))
            .all()
        )
    except Exception:
        return None
    if len(rows) != len(scoped_dataset_ids):
        return None
    items = [
        {
            "dataset_id": str(dataset_id),
            "updated_at": updated_at.isoformat() if updated_at is not None else None,
        }
        for dataset_id, updated_at in rows
    ]
    items.sort(key=lambda item: item["dataset_id"])
    raw = json.dumps(
        {
            "schema": "mimirq.dify_external_response_corpus.v1",
            "datasets": items,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:32]


def _dify_response_cache_settings_signature() -> dict[str, Any]:
    return {
        "internal_top_k_min": int(settings.DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN),
        "internal_top_k_multiplier": int(settings.DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER),
        "internal_top_k_max": int(settings.DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX),
        "primary_scope_enabled": bool(settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED),
        "primary_min_records": int(settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS),
        "primary_min_top_score": float(settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE),
        "compact_enabled": bool(settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED),
        "compact_min_top_score": float(settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE),
        "compact_relative_score_floor": float(settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR),
        "compact_min_records": int(settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS),
        "fast_candidate_top_k_max": int(settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_CANDIDATE_TOP_K_MAX),
        "fast_response_top_k_max": int(settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX),
        "fast_content_max_chars": int(settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS),
        "fast_total_content_max_chars": int(settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS),
        "enable_reranker": bool(settings.ENABLE_RERANKER),
        "dify_reranker_enabled": bool(settings.DIFY_EXTERNAL_KNOWLEDGE_RERANKER_ENABLED),
        "reranker_provider": str(settings.RERANKER_PROVIDER),
        "reranker_model": settings.RERANKER_MODEL,
        "reranker_top_n": int(settings.RERANKER_TOP_N),
        "metadata_anchor_enabled": bool(settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED),
        "metadata_anchor_preflight_enabled": bool(settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED),
        "metadata_anchor_max_scan": int(settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_SCAN),
        "metadata_anchor_total_budget_ms": int(settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS),
        "metadata_anchor_text_scan_enabled": bool(
            settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_TEXT_SCAN_ENABLED
        ),
        "metadata_anchor_extend_sibling_policy_scope_enabled": bool(
            settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTEND_SIBLING_POLICY_SCOPE_ENABLED
        ),
        "metadata_anchor_extended_scope_max_datasets": int(
            settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTENDED_SCOPE_MAX_DATASETS
        ),
        "mixed_intent_supplement_enabled": bool(settings.DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED),
        "mixed_intent_max_subqueries": int(settings.DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_MAX_SUBQUERIES),
        "mixed_intent_subquery_top_k": int(settings.DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUBQUERY_TOP_K),
        "kg_on_demand_enabled": bool(settings.DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_ENABLED),
        "kg_query_expansion_default": bool(settings.DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED),
        "kg_chunk_injection_default": bool(settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED),
        "kg_chunk_injection_max_chunks_default": int(settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS),
        "kg_chunk_boost_default": bool(settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED),
        "kg_chunk_boost_weight_default": float(settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT),
        "kg_chunk_boost_max_promoted_default": int(settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED),
    }


def _build_dify_response_cache_key(
    *,
    actor: _DifyActor,
    knowledge_id: str,
    query: str,
    retrieval_setting: DifyRetrievalSetting,
    metadata_condition: dict[str, Any] | None,
    scope_plan: DatasetScopePlan,
    top_k: int,
    candidate_top_k: int,
    score_threshold: float,
    policy_plugin_refs: tuple[str, ...],
    corpus_token: str,
) -> str:
    signature = {
        "schema": "mimirq.dify_external_response_cache.v1",
        "tenant_id": str(actor.tenant_id),
        "account_id": actor.account_id,
        "knowledge_id": knowledge_id.strip(),
        "query": query.strip(),
        "retrieval_setting": retrieval_setting.model_dump(mode="json"),
        "metadata_condition": metadata_condition or None,
        "dataset_ids": [str(item) for item in scope_plan.dataset_ids],
        "primary_dataset_ids": [str(item) for item in scope_plan.primary_dataset_ids],
        "expansion_dataset_ids": [str(item) for item in scope_plan.expansion_dataset_ids],
        "strict_scope": bool(scope_plan.strict_scope),
        "matched_terms": list(scope_plan.matched_terms),
        "top_k": int(top_k),
        "candidate_top_k": int(candidate_top_k),
        "score_threshold": float(score_threshold),
        "policy_plugin_refs": list(policy_plugin_refs),
        "corpus_token": corpus_token,
        "settings": _dify_response_cache_settings_signature(),
    }
    raw = json.dumps(signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    digest = hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()
    return f"difyext:{actor.tenant_id}:{digest[:32]}"


_knowledge_mapping_plugin_refs = _service_knowledge_mapping_plugin_refs


def _apply_policy_fallback_candidate_multiplier(candidate_top_k: int, *, multiplier: int) -> int:
    try:
        configured_max = int(settings.DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX)
    except (TypeError, ValueError):
        configured_max = 50
    return _service_apply_policy_fallback_candidate_multiplier(
        candidate_top_k,
        multiplier=multiplier,
        configured_max=configured_max,
    )


def _metadata_condition_to_filter(
    condition: dict[str, Any] | None,
    *,
    allowed_fields: set[str] | None = None,
) -> dict[str, Any] | None:
    try:
        return _service_metadata_condition_to_filter(
            condition,
            allowed_fields=allowed_fields,
        )
    except _MetadataConditionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _dify_metadata_condition_item_to_filter(condition: dict[str, Any]) -> dict[str, Any]:
    try:
        return _service_dify_metadata_condition_item_to_filter(condition)
    except _MetadataConditionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _offload_chunk_content_hydration(
    *,
    request_db: Session,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
) -> dict[str, str]:
    request_db.rollback()
    return await run_blocking_retrieval_call(
        _load_chunk_content_map_with_managed_session,
        tenant_id=tenant_id,
        citations=citations,
    )


def _policy_slot_intent_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs:
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        if policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        for raw_mapping in policy.get("query_expansion_values") or ():
            mapping = dict(raw_mapping) if isinstance(raw_mapping, dict) else {}
            for raw_term in mapping.get("terms") or ():
                term = _first_nonempty_str(raw_term)
                normalized = _normalize_match_term(term)
                if len(normalized) < 3 or normalized in seen:
                    continue
                seen.add(normalized)
                terms.append(term)
    return tuple(terms)


def _query_has_policy_slot_intent(query: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> bool:
    query_term = _normalize_match_term(query)
    if len(query_term) < 3:
        return False
    for term in _policy_slot_intent_terms_for_policy_refs(policy_plugin_refs):
        normalized = _normalize_match_term(term)
        if len(normalized) >= 3 and normalized in query_term:
            return True
    return False


def _query_allows_metadata_anchor_preflight(
    query: str,
    *,
    query_prefers_question_anchor: bool,
    query_prefers_service_anchor: bool,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    if _query_blocks_metadata_anchor_preflight(query, policy_plugin_refs=policy_plugin_refs):
        return False
    if _query_has_mixed_intent_for_policy(query, policy_plugin_refs=policy_plugin_refs):
        if (
            query_prefers_service_anchor
            and not _query_has_quoted_anchor_candidate(query)
            and any(
                marker in query
                for marker in ("合并回答", "一并回答", "一起回答", "分别回答", "分开回答", "请合并", "请分别")
            )
        ):
            return False
        return bool(
            query_prefers_service_anchor
            or (
                _query_has_quoted_anchor_candidate(query)
                and _query_has_policy_slot_intent(query, policy_plugin_refs=policy_plugin_refs)
            )
        )
    if (
        query_prefers_question_anchor
        and not query_prefers_service_anchor
        and _query_has_policy_slot_intent(query, policy_plugin_refs=policy_plugin_refs)
    ):
        return False
    return bool(query_prefers_question_anchor or query_prefers_service_anchor)


def _mixed_intent_retrieval_queries(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    text = query.strip()
    if not _query_has_mixed_intent_for_policy(text, policy_plugin_refs=policy_plugin_refs):
        return ()

    max_queries = max(
        1,
        min(
            5,
            int(settings.DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_MAX_SUBQUERIES),
        ),
    )
    out: list[str] = []
    seen: set[str] = {_normalize_match_term(text)}
    quoted_subject_anchor = next(iter(_quoted_query_anchor_display_terms(text)), "")
    subject_anchor = quoted_subject_anchor
    for raw_segment in _MIXED_INTENT_SPLIT_RE.split(text):
        subject_anchor = _append_mixed_intent_queries_for_segment_parts(
            raw_segment,
            out,
            seen=seen,
            max_queries=max_queries,
            subject_anchor=subject_anchor,
            quoted_subject_anchor=quoted_subject_anchor,
            policy_plugin_refs=policy_plugin_refs,
        )
        if len(out) >= max_queries:
            break
    for fallback_query in _mixed_intent_policy_slot_queries_from_inferred_subject(
        text,
        policy_plugin_refs=policy_plugin_refs,
    ):
        if _append_unique_mixed_intent_query(out, seen, fallback_query, max_queries=max_queries):
            break
    return tuple(out)


def _record_mixed_intent_subquery_bonus(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    if not _query_has_mixed_intent_for_policy(query, policy_plugin_refs=policy_plugin_refs):
        return 0.0
    query_term = _normalize_match_term(query)
    best = 0.0
    for metadata in _iter_record_metadata_layers(record):
        subquery = str(metadata.get("dify_mixed_intent_subquery") or "").strip()
        if not subquery:
            continue
        subquery_term = _normalize_match_term(subquery)
        if not subquery_term or subquery_term == query_term:
            continue
        question_bonus = _record_question_intent_bonus(
            record,
            query=subquery,
            policy_plugin_refs=policy_plugin_refs,
        )
        subquery_bonus = (
            0.1
            + _record_metadata_anchor_bonus(record, query=subquery)
            + _record_intent_bonus(record, query=subquery, policy_plugin_refs=policy_plugin_refs)
            + question_bonus
        )
        subquery_cap = 1.4 if question_bonus > 0 else 0.24
        best = max(
            best,
            min(subquery_bonus, subquery_cap),
        )
    return min(best, 1.4)


def _record_rank_score(record: dict[str, Any], *, query: str, policy_plugin_refs: tuple[str, ...] = ()) -> float:
    return (
        float(record.get("score") or 0.0)
        + _record_metadata_anchor_bonus(record, query=query)
        + _record_intent_bonus(record, query=query, policy_plugin_refs=policy_plugin_refs)
        + _record_exact_primary_alias_bonus(record, query=query)
        + _record_url_evidence_bonus(record, query=query)
        + _record_question_intent_bonus(record, query=query, policy_plugin_refs=policy_plugin_refs)
        + _record_answerfulness_score(record, policy_plugin_refs=policy_plugin_refs)
        + _record_mixed_intent_subquery_bonus(record, query=query, policy_plugin_refs=policy_plugin_refs)
        + record_retrieval_policy_bonus(
            record,
            query=query,
            plugin_ref_for_record=lambda candidate: _record_plugin_ref(
                candidate, fallback_plugin_refs=policy_plugin_refs
            ),
            metadata_layers_for_record=_iter_record_metadata_layers,
            policy_resolver=_retrieval_policy_for_plugin_ref,
        )
    )


def _compact_records_for_response(
    records: list[dict[str, Any]],
    *,
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    return _service_compact_records_for_response(
        records,
        query=query,
        top_k=top_k,
        policy_plugin_refs=policy_plugin_refs,
        query_has_mixed_intent_for_policy=lambda raw_query, refs: _query_has_mixed_intent_for_policy(
            raw_query,
            policy_plugin_refs=refs,
        ),
        compact_mixed_intent_exact_anchor_records=lambda items, raw_query, raw_top_k, refs: (
            _compact_mixed_intent_exact_anchor_records(
                items,
                query=raw_query,
                top_k=raw_top_k,
                policy_plugin_refs=refs,
            )
        ),
        strong_question_anchor_records=lambda items, raw_query, refs: _strong_question_anchor_records(
            items,
            query=raw_query,
            policy_plugin_refs=refs,
        ),
        query_has_quoted_anchor_candidate=_query_has_quoted_anchor_candidate,
        compact_exact_anchor_answer_record=lambda items, raw_query, refs: _compact_exact_anchor_answer_record(
            items,
            query=raw_query,
            policy_plugin_refs=refs,
        ),
        compaction_enabled=bool(settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED),
        response_compaction_for_records=lambda items, refs: _response_compaction_for_records(
            items,
            policy_plugin_refs=refs,
        ),
        record_has_strong_question_anchor=lambda item, raw_query, refs: _record_has_strong_question_anchor(
            item,
            query=raw_query,
            policy_plugin_refs=refs,
        ),
        compact_by_strong_question_anchor=lambda items, raw_query, refs: _compact_by_strong_question_anchor(
            items,
            query=raw_query,
            policy_plugin_refs=refs,
        ),
        filter_records_by_retrieval_policy_alignment=lambda items, raw_query, refs: (
            filter_records_by_retrieval_policy_alignment(
                items,
                query=raw_query,
                plugin_ref_for_record=lambda item: _record_plugin_ref(item, fallback_plugin_refs=refs),
                metadata_layers_for_record=_iter_record_metadata_layers,
                policy_resolver=_retrieval_policy_for_plugin_ref,
            )
        ),
        record_rank_score=lambda item, raw_query, refs: _record_rank_score(
            item,
            query=raw_query,
            policy_plugin_refs=refs,
        ),
        compact_high_confidence_items=_compact_high_confidence_for_response,
        default_min_top_score=float(settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE),
        default_relative_score_floor=float(settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR),
        default_min_items=int(settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS),
    )


def _compact_exact_anchor_answer_record(
    records: list[dict[str, Any]], *, query: str, policy_plugin_refs: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    requested_slots = _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
    candidates = [
        record
        for record in records
        if _record_exact_query_anchor_terms(record, query=query, policy_plugin_refs=policy_plugin_refs)
        and _record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs)
        and _record_covers_requested_policy_slots(record, requested_slots, policy_plugin_refs=policy_plugin_refs)
    ]
    if not candidates:
        return []
    _sort_records_for_query(candidates, query=query, policy_plugin_refs=policy_plugin_refs)
    return [candidates[0]]


def _compact_mixed_intent_exact_anchor_records(
    records: list[dict[str, Any]],
    *,
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    return _service_compact_mixed_intent_exact_anchor_records(
        records,
        query=query,
        top_k=top_k,
        policy_plugin_refs=policy_plugin_refs,
        requested_policy_slot_specs_for_query=lambda raw_query, refs: _requested_policy_slot_specs_for_query(
            raw_query,
            policy_plugin_refs=refs,
        ),
        composite_record_for_exact_anchor_slots=lambda items, raw_query, requested_slot_specs, refs: (
            _composite_record_for_exact_anchor_slots(
                items,
                query=raw_query,
                requested_slot_specs=requested_slot_specs,
                policy_plugin_refs=refs,
            )
        ),
        query_has_quoted_anchor_candidate=_query_has_quoted_anchor_candidate,
        record_exact_query_anchor_terms=lambda item, raw_query, refs: _record_exact_query_anchor_terms(
            item,
            query=raw_query,
            policy_plugin_refs=refs,
        ),
        record_content_is_answerful=lambda item, refs: _record_content_is_answerful(
            item,
            policy_plugin_refs=refs,
        ),
        records_have_confident_metadata_anchor=lambda items, raw_query, refs: _records_have_confident_metadata_anchor(
            items,
            query=raw_query,
            policy_plugin_refs=refs,
        ),
        record_has_any_requested_slot_field=_record_has_any_requested_slot_field,
        compact_exact_anchor_answer_record=lambda items, raw_query, refs: _compact_exact_anchor_answer_record(
            items,
            query=raw_query,
            policy_plugin_refs=refs,
        ),
    )


def _sort_records_for_query(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> None:
    anchor_binding_scores = record_retrieval_policy_anchor_binding_scores(
        records,
        query=query,
        plugin_ref_for_record=lambda item: _record_plugin_ref(item, fallback_plugin_refs=policy_plugin_refs),
        metadata_layers_for_record=_iter_record_metadata_layers,
        policy_resolver=_retrieval_policy_for_plugin_ref,
    )
    exact_anchor_scores = _record_exact_anchor_protection_scores(
        records,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    records.sort(
        key=lambda item: (
            _record_rank_score(item, query=query, policy_plugin_refs=policy_plugin_refs)
            + anchor_binding_scores.get(id(item), 0.0)
            + exact_anchor_scores.get(id(item), 0.0)
        ),
        reverse=True,
    )


async def _final_rerank_records_for_query(
    records: list[dict[str, Any]],
    *,
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    provider = _final_rerank_provider(records)
    if provider is None:
        return records
    candidates, id_to_record, candidate_count = _final_rerank_candidates(
        records,
        top_k=top_k,
        policy_plugin_refs=policy_plugin_refs,
    )

    if len(candidates) <= 1:
        return records

    try:
        reranker = get_reranker(provider)
        start = time.perf_counter()
        result = await run_blocking_retrieval_call(
            reranker.rerank,
            query,
            candidates,
            top_n=len(candidates),
            tenant_id=None,
            query_type=None,
        )
        elapsed_sec = result.elapsed_sec if result.elapsed_sec is not None else time.perf_counter() - start
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dify external final reranker failed (%s): %s", provider, exc, exc_info=True)
        return records

    ordered = _ordered_final_rerank_records(
        candidates,
        id_to_record=id_to_record,
        provider=provider,
        result=result,
        elapsed_sec=elapsed_sec,
    )
    if not ordered:
        return records
    reranked_records = ordered + records[candidate_count:]
    _sort_records_for_query(reranked_records, query=query, policy_plugin_refs=policy_plugin_refs)
    return reranked_records


def _final_rerank_provider(records: list[dict[str, Any]]) -> str | None:
    if len(records) <= 1:
        return None
    if not any(_record_needs_final_rerank(record) for record in records):
        return None
    if not _dify_external_reranker_enabled():
        return None
    provider = settings.RERANKER_PROVIDER.strip().lower()
    return None if provider in {"none", "off", "false", "0"} else provider


def _record_answerfulness_score(record: dict[str, Any], *, policy_plugin_refs: tuple[str, ...] = ()) -> float:
    content = record["content"].strip()
    if not content:
        return 0.0
    if _record_has_answer_evidence(record, content=content, policy_plugin_refs=policy_plugin_refs):
        return _ANSWERFUL_RECORD_BONUS
    if _record_is_anchor_only_qa(record, content=content, policy_plugin_refs=policy_plugin_refs):
        return -_ANCHOR_ONLY_QA_RECORD_PENALTY
    return 0.0


def _composite_record_for_exact_anchor_slots(
    records: list[dict[str, Any]],
    *,
    query: str,
    requested_slot_specs: tuple[tuple[str, str], ...],
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    groups = _exact_anchor_slot_record_groups(
        records,
        query=query,
        requested_slot_specs=requested_slot_specs,
        policy_plugin_refs=policy_plugin_refs,
    )
    best_records, best_covered = _best_exact_anchor_slot_group_records(
        groups,
        requested_slot_specs=requested_slot_specs,
    )
    if len(best_records) < 2:
        return None

    first = best_records[0]
    metadata = dict(first.get("metadata") if isinstance(first.get("metadata"), dict) else {})
    metadata.update(
        _composite_exact_anchor_slot_metadata(
            best_records,
            requested_slot_specs=requested_slot_specs,
            best_covered=best_covered,
        )
    )
    score = min(1.0, max((float(record.get("score") or 0.0) for record in best_records), default=0.0) + 0.01)
    return {
        "content": _composite_exact_anchor_slot_content(best_records),
        "score": score,
        "title": str(first.get("title") or "composite-anchor-evidence"),
        "metadata": metadata,
    }


def _composite_exact_anchor_slot_metadata(
    records: list[dict[str, Any]],
    *,
    requested_slot_specs: tuple[tuple[str, str], ...],
    best_covered: set[tuple[str, str]],
) -> dict[str, Any]:
    source_chunk_ids: list[str] = []
    source_document_ids: list[str] = []
    for record in records:
        record_metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        chunk_id = str(record_metadata.get("chunk_id") or "").strip()
        document_id = str(record_metadata.get("document_id") or "").strip()
        if chunk_id and chunk_id not in source_chunk_ids:
            source_chunk_ids.append(chunk_id)
        if document_id and document_id not in source_document_ids:
            source_document_ids.append(document_id)
    covered_specs = [
        {"metadata": field, "value": value}
        for field, value in requested_slot_specs
        if (field, _normalize_match_term(value)) in best_covered
    ]
    metadata = {
        "dify_composite_exact_anchor_slots": True,
        "dify_composite_slot_specs": covered_specs,
        "dify_composite_source_chunk_ids": source_chunk_ids,
        "dify_composite_source_document_ids": source_document_ids,
    }
    section_types = [spec["value"] for spec in covered_specs if spec["metadata"] == "section_type"]
    if section_types:
        metadata["section_type"] = "composite"
        metadata["dify_composite_section_types"] = section_types
    return metadata


def _record_is_anchor_only_qa(
    record: dict[str, Any],
    *,
    content: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    response_hints = _response_hints_for_record(record, policy_plugin_refs=policy_plugin_refs)
    normalized = content.strip()
    answer_labels = _response_hint_string_list(response_hints, "answer_labels")
    answer_keywords = _response_hint_string_list(response_hints, "answer_keywords")
    if any(label and label in normalized for label in (*answer_labels, *answer_keywords)):
        return False
    chunk_kinds = set(_response_hint_string_list(response_hints, "anchor_only_chunk_kinds"))
    if not chunk_kinds:
        return False
    is_qa_record = any(
        str(metadata.get("chunk_kind") or "").strip() in chunk_kinds
        for metadata in _iter_record_metadata_layers(record)
    )
    if not is_qa_record:
        return False
    markers = _response_hint_string_list(response_hints, "anchor_only_markers")
    return any(marker and marker in normalized for marker in markers)


def _records_can_skip_kg_on_demand(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    if _query_prefers_service_anchor(query, policy_plugin_refs=policy_plugin_refs):
        return _records_have_confident_metadata_anchor(
            records,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        ) or _records_meet_primary_scope(
            records,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
    if _query_prefers_question_anchor(query, policy_plugin_refs=policy_plugin_refs):
        return _records_have_strong_question_anchor(
            records,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
    return _records_have_confident_metadata_anchor(
        records,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )


def _dedupe_records(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    return _service_dedupe_records(
        records,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
        record_dedupe_key=_record_dedupe_key,
        record_rank_score=lambda item, raw_query, refs: _record_rank_score(
            item,
            query=raw_query,
            policy_plugin_refs=refs,
        ),
    )


async def _offload_dify_kg_chunk_rows(
    *,
    request_db: Session,
    tenant_id: UUID,
    dataset_ids: list[UUID],
    chunk_ids: list[UUID],
) -> list[Any]:
    request_db.rollback()
    return await run_blocking_retrieval_call(
        _load_dify_kg_chunk_rows_with_managed_session,
        tenant_id=tenant_id,
        dataset_ids=dataset_ids,
        chunk_ids=chunk_ids,
    )


async def _dify_kg_on_demand_records(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_ids: list[UUID],
    query: str,
    requested_kg_flags: _DifyKGFlags,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    scoped_dataset_ids = _dify_kg_on_demand_dataset_ids(
        dataset_ids,
        requested_kg_flags=requested_kg_flags,
    )
    if not scoped_dataset_ids:
        return []

    try:
        from app.rag.kg.pipeline import kg_search

        kg_result = await kg_search(
            query=query,
            tenant_id=tenant_id,
            dataset_ids=scoped_dataset_ids,
            account_id=account_id,
        )
    except Exception:
        logger.debug("Dify KG on-demand search failed", exc_info=True)
        return []

    events = kg_result.get("events") if isinstance(kg_result, dict) else []
    events = events if isinstance(events, list) else []
    if not events:
        return []

    chunk_events = _dify_kg_chunk_events(
        events,
        max_records=_dify_kg_on_demand_max_records(requested_kg_flags),
    )
    if not chunk_events:
        return []

    try:
        rows = await _offload_dify_kg_chunk_rows(
            request_db=db,
            tenant_id=tenant_id,
            dataset_ids=scoped_dataset_ids,
            chunk_ids=[chunk_id for chunk_id, _event in chunk_events],
        )
    except Exception:
        logger.debug("Dify KG on-demand chunk hydration failed", exc_info=True)
        return []

    return _dify_kg_records_from_rows(
        rows,
        chunk_events=chunk_events,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )


def _dify_kg_records_from_rows(
    rows: list[Any],
    *,
    chunk_events: list[tuple[UUID, dict[str, Any]]],
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    row_by_chunk_id = {UUID(str(_row_value(row, "chunk_id"))): row for row in rows}
    records: list[dict[str, Any]] = []
    for chunk_id, event in chunk_events:
        row = row_by_chunk_id.get(chunk_id)
        if row is None:
            continue
        citation, dataset_id = _dify_kg_record_citation(row, chunk_id=chunk_id, event=event)
        record = _citation_to_dify_record(
            citation,
            dataset_id=dataset_id,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        if record["content"].strip():
            records.append(record)
    return records


def _records_meet_primary_scope(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    min_records = max(1, settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS)
    if len(records) < min_records:
        return False
    min_top_score = settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE
    if min_top_score <= 0:
        return True
    top_score = max(
        _record_rank_score(record, query=query, policy_plugin_refs=policy_plugin_refs) for record in records
    )
    return top_score >= min_top_score


def _metadata_anchor_fallback_record_score(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    content = record["content"].strip()
    if content and _record_is_anchor_only_qa(record, content=content, policy_plugin_refs=policy_plugin_refs):
        return 0.0
    question_strength = _record_question_anchor_strength(
        record,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    anchor_bonus = _record_metadata_anchor_bonus(record, query=query)
    intent_bonus = _record_intent_bonus(record, query=query, policy_plugin_refs=policy_plugin_refs)
    policy_bonus = record_retrieval_policy_bonus(
        record,
        query=query,
        plugin_ref_for_record=lambda item: _record_plugin_ref(item, fallback_plugin_refs=policy_plugin_refs),
        metadata_layers_for_record=_iter_record_metadata_layers,
        policy_resolver=_retrieval_policy_for_plugin_ref,
    )
    has_strong_question_anchor = _record_has_strong_question_anchor(
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
    if _records_can_skip_metadata_anchor_fallback(
        existing_records or [],
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return []

    scoped_dataset_ids = {_coerce_uuid_text(dataset_id) for dataset_id in dataset_ids or []}
    scoped_dataset_ids.discard("")
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
    _sort_records_for_query(candidates, query=query, policy_plugin_refs=policy_plugin_refs)
    composite = _metadata_anchor_exact_slot_composite(
        candidates,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    if composite is not None:
        return [composite]
    merged = _dedupe_records(candidates, query=query, policy_plugin_refs=policy_plugin_refs)
    _sort_records_for_query(merged, query=query, policy_plugin_refs=policy_plugin_refs)
    limit = max(
        1,
        min(
            max(1, int(top_k or 1)),
            int(settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_RECORDS),
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
    content = _row_value(row, "content").strip()
    if not content:
        return None
    metadata = _metadata_anchor_row_metadata(row, dataset_id=dataset_id)
    record = {
        "content": _content_with_answer_hints(
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


def _metadata_anchor_exact_slot_composite(
    candidates: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    if not _query_has_mixed_intent_for_policy(query, policy_plugin_refs=policy_plugin_refs):
        return None
    requested_slots = _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
    if not requested_slots:
        return None
    return _composite_record_for_exact_anchor_slots(
        candidates,
        query=query,
        requested_slot_specs=requested_slots,
        policy_plugin_refs=policy_plugin_refs,
    )


def _metadata_anchor_db_fallback_plan(
    query: str,
    *,
    terms: list[str],
    policy_plugin_refs: tuple[str, ...] = (),
    prefer_question_anchor_first: bool,
) -> _MetadataAnchorDBFallbackPlan:
    question_anchor_preferred = _query_prefers_question_anchor(query, policy_plugin_refs=policy_plugin_refs)
    service_anchor_preferred = _query_prefers_service_anchor(query, policy_plugin_refs=policy_plugin_refs)
    query_has_slot_question_intent = bool(
        _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
        or _query_intent_terms(
            query,
            intent_terms=_question_anchor_intent_terms_for_policy_refs(policy_plugin_refs),
        )
    )
    question_anchor_first = _metadata_anchor_should_query_question_first(
        query,
        query_prefers_question_anchor=question_anchor_preferred,
        query_prefers_service_anchor=service_anchor_preferred,
        prefer_question_anchor_first=bool(prefer_question_anchor_first),
        policy_plugin_refs=policy_plugin_refs,
    )
    requested_slot_specs = _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
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
        service_anchor_fields=_anchor_binding_fields_for_policy_refs(policy_plugin_refs) or ("service_name",),
        mixed_intent_retrieval_queries=_mixed_intent_retrieval_queries(query, policy_plugin_refs=policy_plugin_refs),
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
        _query_has_mixed_intent_for_policy(ctx.query, policy_plugin_refs=ctx.policy_plugin_refs)
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
        _query_has_mixed_intent_for_policy(ctx.query, policy_plugin_refs=ctx.policy_plugin_refs)
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
    if _compact_mixed_intent_exact_anchor_records(
        current_matches,
        query=ctx.query,
        top_k=ctx.top_k,
        policy_plugin_refs=ctx.policy_plugin_refs,
    ):
        return current_matches
    _metadata_anchor_rewind(ctx, rows_before=rows_before, seen_before=seen_before)
    return None


def _metadata_anchor_quoted_slot_matches(
    ctx: _MetadataAnchorDBFallbackContext,
    plan: _MetadataAnchorDBFallbackPlan,
) -> list[dict[str, Any]] | None:
    if not (
        _query_has_mixed_intent_for_policy(ctx.query, policy_plugin_refs=ctx.policy_plugin_refs)
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
    if _compact_mixed_intent_exact_anchor_records(
        current_matches,
        query=ctx.query,
        top_k=ctx.top_k,
        policy_plugin_refs=ctx.policy_plugin_refs,
    ):
        return current_matches
    return None


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
            conditions,
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
    account_id: str,
    dataset_ids: list[UUID],
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
    existing_records: list[dict[str, Any]] | None = None,
    metadata_filter: dict[str, Any] | None = None,
    prefer_question_anchor_first: bool = False,
    max_elapsed_ms: int | None = None,
) -> tuple[_MetadataAnchorDBFallbackContext, _MetadataAnchorDBFallbackPlan] | None:
    if not bool(settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED):
        return None
    if metadata_filter:
        return None
    if _records_can_skip_metadata_anchor_fallback(
        existing_records or [],
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return None
    scoped_dataset_ids = _dedupe_dataset_ids(list(dataset_ids or []))
    if not scoped_dataset_ids:
        return None
    terms = _metadata_anchor_fallback_query_terms(query)
    if not terms:
        return None
    max_scan = max(
        1,
        min(
            500,
            int(settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_SCAN),
        ),
    )
    started = time.perf_counter()
    ctx = _MetadataAnchorDBFallbackContext(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
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
        ctx.db.rollback()
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
            ctx.db.rollback()
    return _metadata_anchor_fallback_records_from_rows(
        ctx.rows,
        dataset_ids=ctx.scoped_dataset_ids,
        query=ctx.query,
        top_k=ctx.top_k,
        policy_plugin_refs=ctx.policy_plugin_refs,
        existing_records=ctx.existing_records,
    )


def _metadata_anchor_db_fallback_records(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
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
        account_id=account_id,
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


def _metadata_anchor_db_fallback_records_with_managed_session(
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
        return _metadata_anchor_db_fallback_records(db=worker_db, **kwargs)
    finally:
        worker_db.close()


async def _retrieve_dataset_citations(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_ids: list[UUID],
    query: str,
    top_k: int,
    score_threshold: float,
    metadata_filter: dict[str, Any] | None = None,
    requested_top_k: int,
    enable_kg_query_expansion: bool,
    enable_kg_chunk_injection: bool,
    kg_chunk_injection_max_chunks: int | None = None,
    enable_kg_chunk_boost: bool,
    kg_chunk_boost_weight: float | None = None,
    kg_chunk_boost_max_promoted: int | None = None,
    enable_reranker: bool,
    retrieval_mode: str = "hybrid",
) -> list[dict[str, Any]]:
    from app.api.schemas.conversations import EvidenceRetrieveRequest
    from app.services.retrieval_requests import retrieve_evidence

    started = time.perf_counter()
    evidence_top_k = max(1, top_k)

    overfetch_multiplier = max(
        1,
        settings.DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MULTIPLIER,
    )
    overfetch_max_k = max(
        0,
        settings.DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MAX_K,
    )
    if overfetch_max_k <= 0:
        overfetch_max_k = evidence_top_k

    reranker_top_n = max(evidence_top_k, settings.RERANKER_TOP_N)
    rag_config = ChatRAGConfig(
        top_k=evidence_top_k,
        score_threshold=score_threshold,
        retrieval_mode=retrieval_mode,
        visible_evidence_only=True,
        metadata_filter=metadata_filter,
        enable_reranker=enable_reranker,
        reranker_provider=settings.RERANKER_PROVIDER if enable_reranker else "none",
        reranker_top_n=reranker_top_n,
        lexical_db_hybrid_fallback_only=settings.DIFY_EXTERNAL_KNOWLEDGE_LEXICAL_DB_HYBRID_FALLBACK_ONLY,
        lexical_db_hybrid_metadata_exact_fallback_enabled=(
            settings.DIFY_EXTERNAL_KNOWLEDGE_LEXICAL_METADATA_EXACT_FALLBACK_ENABLED
        ),
        metadata_exact_db_fallback_enabled=settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_EXACT_DB_FALLBACK_ENABLED,
        retrieval_overfetch_multiplier=overfetch_multiplier,
        retrieval_overfetch_max_k=overfetch_max_k,
        enable_kg_query_expansion=enable_kg_query_expansion,
        enable_kg_chunk_injection=enable_kg_chunk_injection,
        kg_chunk_injection_max_chunks=(
            _dify_kg_int("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS", 3)
            if kg_chunk_injection_max_chunks is None
            else kg_chunk_injection_max_chunks
        ),
        enable_kg_chunk_boost=enable_kg_chunk_boost,
        kg_chunk_boost_weight=(
            _dify_kg_float("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT", 0.25)
            if kg_chunk_boost_weight is None
            else kg_chunk_boost_weight
        ),
        kg_chunk_boost_max_promoted=(
            _dify_kg_int("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED", 2)
            if kg_chunk_boost_max_promoted is None
            else kg_chunk_boost_max_promoted
        ),
    )

    scoped_dataset_ids = _dedupe_dataset_ids(dataset_ids)
    response = await retrieve_evidence(
        body=EvidenceRetrieveRequest(query=query, rag_config=rag_config, dataset_ids=scoped_dataset_ids),
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    metrics = response.metrics
    trace = response.retrieval_trace or {}
    logger.info(
        "Dify evidence retrieve completed query_hash=%s dataset_count=%s top_k=%s requested_top_k=%s "
        "citations=%s elapsed_ms=%s retrieval_elapsed_sec=%s vector_backend=%s retrieval_mode=%s "
        "post_rerank_elapsed_sec=%s hard_fallback_elapsed_sec=%s trace_passes=%s",
        _diagnostic_query_hash(query),
        len(scoped_dataset_ids),
        evidence_top_k,
        requested_top_k,
        len(response.citations),
        elapsed_ms,
        metrics.get("retrieval_elapsed_sec"),
        metrics.get("vector_backend"),
        metrics.get("retrieval_mode") or metrics.get("requested_retrieval_mode"),
        metrics.get("evidence_post_rerank_elapsed_sec"),
        metrics.get("hard_fallback_elapsed_sec"),
        len(trace.get("passes") or []),
    )
    return list(response.citations)


def _resolve_dify_warmup_tenant_id() -> UUID | None:
    raw_tenant = (settings.DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID or settings.DEFAULT_TENANT_ID).strip()
    if not raw_tenant:
        return None
    try:
        return UUID(raw_tenant)
    except ValueError:
        logger.warning("Skipping Dify external warmup: tenant id is invalid", exc_info=True)
        return None


def _resolve_dify_warmup_query() -> str:
    query = settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_QUERY.strip()
    return query or _DIFY_WARMUP_DEFAULT_QUERY


def _resolve_dify_warmup_top_k() -> int:
    configured_top_k = settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TOP_K
    configured_max = settings.DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX
    return max(1, min(configured_top_k, max(1, configured_max)))


def _resolve_dify_warmup_timeout_sec() -> float:
    return max(1.0, settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC)


def _resolve_dify_warmup_start_delay_sec() -> float:
    return max(0.0, min(60.0, settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_START_DELAY_SEC))


async def warmup_dify_external_knowledge(
    *,
    db_factory: Callable[[], Session] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    disabled_result = _dify_external_warmup_disabled_result()
    if disabled_result is not None:
        return disabled_result
    _set_dify_external_warmup_status(
        enabled=True,
        status="running",
        attempted=0,
        completed=0,
        failed=0,
        elapsed_ms=None,
    )

    try:
        knowledge_map = _load_knowledge_map()
    except Exception:  # noqa: BLE001
        logger.warning("Skipping Dify external warmup: knowledge map is invalid", exc_info=True)
        return _dify_external_warmup_status_result(
            enabled=True,
            status="failed",
            reason="invalid_knowledge_map",
            started=started,
            failed=1,
        )

    knowledge_ids = _resolve_dify_warmup_knowledge_ids(knowledge_map)
    tenant_id = _resolve_dify_warmup_tenant_id()
    skip_reason = _dify_external_warmup_skip_reason(
        knowledge_ids,
        tenant_id=tenant_id,
    )
    if skip_reason is not None:
        return _dify_external_warmup_status_result(
            enabled=True,
            status="skipped",
            reason=skip_reason,
            started=started,
        )
    if not _dify_warmup_can_use_retrieval_slot():
        return _dify_external_warmup_status_result(
            enabled=True,
            status="skipped",
            reason="warmup_skipped_single_retrieval_slot",
            started=started,
        )
    _set_dify_external_warmup_status(enabled=True, status="running", attempted=len(knowledge_ids))

    factory = db_factory if db_factory is not None else SessionLocal
    account_id = settings.DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID.strip()
    query = _resolve_dify_warmup_query()
    top_k = _resolve_dify_warmup_top_k()
    score_threshold = 0.0
    timeout_sec = _resolve_dify_warmup_timeout_sec()
    warmup_lease, warmup_lease_ttl_sec = await _acquire_dify_warmup_lease(
        knowledge_count=len(knowledge_ids),
        timeout_sec=timeout_sec,
    )
    if warmup_lease is None:
        return _dify_external_warmup_locked_result(
            started=started,
            warmup_lease_ttl_sec=warmup_lease_ttl_sec,
        )
    lease_heartbeat_task = _dify_external_warmup_lease_task(warmup_lease, warmup_lease_ttl_sec)
    completed = 0
    failed = 0

    try:
        for knowledge_id in knowledge_ids:
            success = await _run_dify_external_warmup_iteration(
                knowledge_id,
                factory=factory,
                tenant_id=tenant_id,
                account_id=account_id,
                query=query,
                top_k=top_k,
                score_threshold=score_threshold,
                timeout_sec=timeout_sec,
            )
            completed += int(success)
            failed += int(not success)
    finally:
        if lease_heartbeat_task is not None:
            lease_heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await lease_heartbeat_task
        await _release_distributed_dify_response_lease(warmup_lease)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    result = {
        "enabled": True,
        "reason": "completed",
        "attempted": len(knowledge_ids),
        "completed": completed,
        "failed": failed,
        "elapsed_ms": elapsed_ms,
    }
    _set_dify_external_warmup_status(
        enabled=True,
        status="completed" if failed == 0 else "failed",
        attempted=len(knowledge_ids),
        completed=completed,
        failed=failed,
        elapsed_ms=elapsed_ms,
    )
    logger.info(
        "Dify external warmup finished attempted=%s completed=%s failed=%s elapsed_ms=%s",
        result["attempted"],
        completed,
        failed,
        elapsed_ms,
        extra={"event": "dify_external_warmup", "phase": "finished", **result},
    )
    return result


def _dify_external_warmup_disabled_result() -> dict[str, Any] | None:
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED:
        _set_dify_external_warmup_status(
            enabled=False,
            status="disabled",
            attempted=0,
            completed=0,
            failed=0,
            elapsed_ms=0,
        )
        return {
            "enabled": False,
            "reason": "external_knowledge_disabled",
            "attempted": 0,
            "completed": 0,
            "failed": 0,
        }
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED:
        _set_dify_external_warmup_status(
            enabled=True,
            status="disabled",
            attempted=0,
            completed=0,
            failed=0,
            elapsed_ms=0,
        )
        return {
            "enabled": False,
            "reason": "warmup_disabled",
            "attempted": 0,
            "completed": 0,
            "failed": 0,
        }
    return None


def _dify_external_warmup_skip_reason(
    knowledge_ids: tuple[str, ...],
    *,
    tenant_id: UUID | None,
) -> str | None:
    if tenant_id is None:
        return "tenant_not_configured"
    if not knowledge_ids:
        return "no_knowledge_ids"
    return None


def _dify_external_warmup_status_result(
    *,
    enabled: bool,
    status: str,
    reason: str,
    started: float,
    attempted: int = 0,
    completed: int = 0,
    failed: int = 0,
) -> dict[str, Any]:
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    _set_dify_external_warmup_status(
        enabled=enabled,
        status=status,
        attempted=attempted,
        completed=completed,
        failed=failed,
        elapsed_ms=elapsed_ms,
    )
    return {
        "enabled": enabled,
        "reason": reason,
        "attempted": attempted,
        "completed": completed,
        "failed": failed,
        "elapsed_ms": elapsed_ms,
    }


def _dify_external_warmup_locked_result(
    *,
    started: float,
    warmup_lease_ttl_sec: int | None,
) -> dict[str, Any]:
    result = _dify_external_warmup_status_result(
        enabled=True,
        status="skipped",
        reason="warmup_lease_unavailable" if warmup_lease_ttl_sec is None else "warmup_locked",
        started=started,
    )
    if warmup_lease_ttl_sec is not None:
        result["retry_after_sec"] = warmup_lease_ttl_sec
    return result


def _dify_external_warmup_lease_task(
    warmup_lease: _DifyDistributedLease | None,
    warmup_lease_ttl_sec: int | None,
) -> asyncio.Task[Any] | None:
    if warmup_lease is None or warmup_lease_ttl_sec is None:
        return None
    return asyncio.create_task(
        _maintain_best_effort_dify_lease(
            warmup_lease,
            ttl_sec=warmup_lease_ttl_sec,
        )
    )


async def _run_dify_external_warmup_iteration(
    knowledge_id: str,
    *,
    factory: Callable[[], Session],
    tenant_id: UUID,
    account_id: str,
    query: str,
    top_k: int,
    score_threshold: float,
    timeout_sec: float,
) -> bool:
    item_started = time.perf_counter()
    db = None
    try:
        scope_plan = _resolve_knowledge_dataset_scope(knowledge_id, query=query)
        dataset_ids = _primary_scope_dataset_ids(
            scope_plan, primary_scope_enabled=settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED
        )
        db = factory()
        await asyncio.wait_for(
            _retrieve_dataset_citations(
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_ids=dataset_ids,
                query=query,
                top_k=top_k,
                requested_top_k=top_k,
                score_threshold=score_threshold,
                enable_kg_query_expansion=False,
                enable_kg_chunk_injection=False,
                enable_kg_chunk_boost=False,
                enable_reranker=False,
            ),
            timeout=timeout_sec,
        )
        _log_dify_external_warmup_iteration(
            knowledge_id,
            dataset_count=len(dataset_ids),
            item_started=item_started,
            success=True,
        )
        return True
    except Exception:  # noqa: BLE001
        _log_dify_external_warmup_iteration(
            knowledge_id,
            dataset_count=0,
            item_started=item_started,
            success=False,
        )
        return False
    finally:
        if db is not None:
            db.close()


def _log_dify_external_warmup_iteration(
    knowledge_id: str,
    *,
    dataset_count: int,
    item_started: float,
    success: bool,
) -> None:
    item_elapsed_ms = round((time.perf_counter() - item_started) * 1000, 2)
    if success:
        logger.info(
            "Dify external warmup completed knowledge_id_hash=%s dataset_count=%s elapsed_ms=%s",
            _diagnostic_value_hash(knowledge_id),
            dataset_count,
            item_elapsed_ms,
            extra={
                "event": "dify_external_warmup",
                "phase": "knowledge_completed",
                "knowledge_id_hash": _diagnostic_value_hash(knowledge_id),
                "dataset_count": dataset_count,
                "elapsed_ms": item_elapsed_ms,
            },
        )
        return
    logger.warning(
        "Dify external warmup failed knowledge_id_hash=%s elapsed_ms=%s",
        _diagnostic_value_hash(knowledge_id),
        item_elapsed_ms,
        exc_info=True,
        extra={
            "event": "dify_external_warmup",
            "phase": "knowledge_failed",
            "knowledge_id_hash": _diagnostic_value_hash(knowledge_id),
            "elapsed_ms": item_elapsed_ms,
        },
    )


async def _delayed_warmup_dify_external_knowledge() -> dict[str, Any]:
    delay_sec = _resolve_dify_warmup_start_delay_sec()
    if delay_sec > 0:
        await asyncio.sleep(delay_sec)
    else:
        # Yield once so lifespan can return before any cold retrieval work runs.
        await asyncio.sleep(0)
    result = await warmup_dify_external_knowledge()
    if result.get("reason") != "warmup_locked":
        return result

    await asyncio.sleep(max(1, int(result.get("retry_after_sec") or 1)))
    return await warmup_dify_external_knowledge()


def _log_dify_warmup_task_result(task: Any) -> None:
    if isinstance(task, asyncio.Task):
        _dify_external_warmup_tasks.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("Dify external warmup task cancelled")
    except Exception:  # noqa: BLE001
        logger.warning("Dify external warmup task failed", exc_info=True)


def start_dify_external_knowledge_warmup(
    *,
    create_task: Callable[[Any], Any] | None = None,
) -> Any | None:
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED:
        _set_dify_external_warmup_status(enabled=False, status="disabled")
        return None
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED:
        _set_dify_external_warmup_status(enabled=True, status="disabled")
        return None

    delay_sec = _resolve_dify_warmup_start_delay_sec()
    _set_dify_external_warmup_status(enabled=True, status="scheduled", start_delay_sec=delay_sec)
    coro = _delayed_warmup_dify_external_knowledge()
    try:
        task = create_task(coro) if create_task is not None else asyncio.create_task(coro)
    except RuntimeError:
        coro.close()
        logger.warning("Dify external warmup was not scheduled: no running event loop", exc_info=True)
        return None
    except Exception:  # noqa: BLE001
        coro.close()
        logger.warning("Dify external warmup was not scheduled", exc_info=True)
        return None

    if isinstance(task, asyncio.Task):
        _dify_external_warmup_tasks.add(task)
    add_done_callback = getattr(task, "add_done_callback", None)
    if callable(add_done_callback):
        add_done_callback(_log_dify_warmup_task_result)
    logger.info("Dify external warmup scheduled start_delay_sec=%s", delay_sec)
    return task


@router.post(
    "/conversation-turns",
    response_model=DifyConversationTurnResponse,
)
async def persist_dify_conversation_turn(
    body: DifyConversationTurnRequest,
    actor: Annotated[_DifyActor, Depends(_require_dify_actor)],
    db: Annotated[Session, Depends(get_db)],
) -> DifyConversationTurnResponse:
    return await run_blocking_call_with_managed_session(
        lambda worker_db: _persist_dify_conversation_turn(
            db=worker_db,
            tenant_id=actor.tenant_id,
            account_id=actor.account_id,
            query=body.query,
            answer=body.answer,
            trace_request_id=body.trace_request_id,
            source_conversation_id=_dify_turn_source_conversation_id(body),
            source_message_id=_dify_turn_source_message_id(body),
            source_run_id=_dify_turn_source_run_id(body),
            citations=body.citations,
            metadata=body.metadata,
            conversation_id=_uuid_or_none(body.conversation_id),
        ),
        request_db=db,
    )


@router.post("/retrieval")
async def retrieve_external_knowledge(
    request: Request,
    body: DifyExternalKnowledgeRequest,
    actor: Annotated[_DifyActor, Depends(_require_dify_actor)],
    db: Annotated[Session, Depends(get_db)],
) -> DifyExternalKnowledgeResponse:
    return await _retrieve_external_knowledge(request=request, body=body, actor=actor, db=db)


@dataclass
class _DifyExternalRetrievalContext:
    request: Request
    body: DifyExternalKnowledgeRequest
    actor: _DifyActor
    db: Session
    started: float
    scope_plan: DatasetScopePlan
    dataset_ids: list[UUID]
    primary_dataset_ids: list[UUID]
    expansion_dataset_ids: list[UUID]
    top_k: int
    candidate_top_k: int
    response_top_k: int
    latency_profile: str
    fast_latency_profile: bool
    policy_fallback_multiplier: int
    policy_plugin_refs: tuple[str, ...]
    external_reranker_enabled: bool
    score_threshold: float
    metadata_filter: dict[str, Any] | None
    metadata_anchor_dataset_ids: list[UUID]
    requested_kg_flags: _DifyKGFlags
    kg_on_demand_enabled: bool
    primary_kg_flags: _DifyKGFlags
    log_extra_base: dict[str, Any]
    trace_conversation_id: UUID | None
    trace_request_id: str | None
    response_cache_key: str | None
    response_cache_ttl_sec: int
    response_cache_max_entries: int
    response_cache_enabled: bool
    singleflight_enabled: bool
    stage_timings_ms: dict[str, float | int | bool] = dataclass_field(default_factory=dict)
    distributed_singleflight_lease: _DifyDistributedLease | None = None
    distributed_singleflight_lease_task: asyncio.Task[Any] | None = None
    singleflight_key: str | None = None
    singleflight_leader: bool = False
    singleflight_future: asyncio.Future[dict[str, Any]] | None = None
    records: list[dict[str, Any]] = dataclass_field(default_factory=list)
    citation_count: int = 0
    primary_citation_count: int = 0
    expansion_citation_count: int = 0
    mixed_intent_citation_count: int = 0
    mixed_intent_query_count: int = 0
    metadata_anchor_fallback_count: int = 0
    retrieval_path: str = ""
    kg_on_demand_triggered: bool = False
    kg_on_demand_skipped: bool = False
    trace_queries: list[dict[str, Any]] = dataclass_field(default_factory=list)
    query_prefers_question_anchor: bool = False
    query_prefers_service_anchor: bool = False
    metadata_anchor_db_fallback_enabled: bool = False
    metadata_anchor_total_budget_ms: int = 0
    metadata_anchor_budget_spent_ms: float = 0.0


def _primary_scope_dataset_ids(scope_plan: DatasetScopePlan, *, primary_scope_enabled: bool) -> list[UUID]:
    dataset_ids = list(scope_plan.primary_dataset_ids if primary_scope_enabled else scope_plan.dataset_ids)
    return dataset_ids or list(scope_plan.dataset_ids)


def _dify_response_cache_settings() -> tuple[int, int, bool, bool]:
    ttl_sec = max(0, settings.DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_TTL_SEC)
    max_entries = max(0, settings.DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_MAX_ENTRIES)
    enabled = settings.DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED and ttl_sec > 0 and max_entries > 0
    singleflight_enabled = settings.DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_ENABLED
    return ttl_sec, max_entries, enabled, singleflight_enabled


def _build_dify_external_retrieval_context(
    *,
    request: Request,
    body: DifyExternalKnowledgeRequest,
    actor: _DifyActor,
    db: Session,
) -> _DifyExternalRetrievalContext:
    started = time.perf_counter()
    scope_plan = _resolve_knowledge_dataset_scope(body.knowledge_id, query=body.query)
    dataset_ids = list(scope_plan.dataset_ids)
    primary_scope_enabled = settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED
    primary_dataset_ids = _primary_scope_dataset_ids(scope_plan, primary_scope_enabled=primary_scope_enabled)
    expansion_dataset_ids = list(scope_plan.expansion_dataset_ids if primary_scope_enabled else ())
    configured_max = settings.DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX
    top_k = max(1, min(body.retrieval_setting.top_k, configured_max))
    latency_profile = _resolve_dify_latency_profile(body.retrieval_setting)
    fast_latency_profile = latency_profile == "fast"
    candidate_top_k = (
        _dify_fast_candidate_top_k(top_k) if fast_latency_profile else _resolve_internal_candidate_top_k(top_k)
    )
    response_top_k = _dify_fast_response_top_k(top_k) if fast_latency_profile else top_k
    policy_fallback_multiplier = 1
    if not fast_latency_profile:
        policy_fallback_multiplier = _resolve_knowledge_policy_fallback_multiplier(body.knowledge_id)
        candidate_top_k = _apply_policy_fallback_candidate_multiplier(
            candidate_top_k,
            multiplier=policy_fallback_multiplier,
        )
    policy_plugin_refs = _resolve_knowledge_policy_plugin_refs(body.knowledge_id)
    if (
        not fast_latency_profile
        and _query_has_mixed_intent_for_policy(body.query, policy_plugin_refs=policy_plugin_refs)
        and _dify_external_reranker_enabled()
    ):
        candidate_top_k = min(candidate_top_k, top_k)
    score_threshold = _clamp_score(body.retrieval_setting.score_threshold)
    metadata_filter = _metadata_condition_to_filter(
        body.metadata_condition,
        allowed_fields=_resolve_knowledge_policy_filter_fields(body.knowledge_id),
    )
    requested_kg_flags = _resolve_dify_kg_flags(body.retrieval_setting)
    kg_on_demand_enabled = False if fast_latency_profile else settings.DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_ENABLED
    primary_kg_flags = (
        _disabled_dify_kg_flags()
        if fast_latency_profile
        else (_disabled_dify_kg_flags() if requested_kg_flags.enabled and kg_on_demand_enabled else requested_kg_flags)
    )
    response_cache_ttl_sec, response_cache_max_entries, response_cache_enabled, singleflight_enabled = (
        _dify_response_cache_settings()
    )
    return _DifyExternalRetrievalContext(
        request=request,
        body=body,
        actor=actor,
        db=db,
        started=started,
        scope_plan=scope_plan,
        dataset_ids=dataset_ids,
        primary_dataset_ids=primary_dataset_ids,
        expansion_dataset_ids=expansion_dataset_ids,
        top_k=top_k,
        candidate_top_k=candidate_top_k,
        response_top_k=response_top_k,
        latency_profile=latency_profile,
        fast_latency_profile=fast_latency_profile,
        policy_fallback_multiplier=policy_fallback_multiplier,
        policy_plugin_refs=policy_plugin_refs,
        external_reranker_enabled=False if fast_latency_profile else _dify_external_reranker_enabled(),
        score_threshold=score_threshold,
        metadata_filter=metadata_filter,
        metadata_anchor_dataset_ids=_metadata_anchor_dataset_ids_for_query(
            knowledge_id=body.knowledge_id,
            base_dataset_ids=primary_dataset_ids,
            query=body.query,
            policy_plugin_refs=policy_plugin_refs,
        ),
        requested_kg_flags=requested_kg_flags,
        kg_on_demand_enabled=kg_on_demand_enabled,
        primary_kg_flags=primary_kg_flags,
        log_extra_base={
            "event": "dify_external_retrieval",
            "client_ip_hash": _diagnostic_value_hash(_request_client_ip(request)),
            "knowledge_id_hash": _diagnostic_value_hash(body.knowledge_id),
            "query_hash": _diagnostic_query_hash(body.query),
            "knowledge_id_chars": len(body.knowledge_id),
            "query_chars": len(body.query),
            "top_k": top_k,
            "candidate_top_k": candidate_top_k,
            "response_top_k": response_top_k,
            "latency_profile": latency_profile,
            "policy_fallback_multiplier": policy_fallback_multiplier,
            "score_threshold": score_threshold,
            "dataset_count": len(dataset_ids),
            "primary_dataset_count": len(primary_dataset_ids),
            "expansion_dataset_count": len(expansion_dataset_ids),
            "route_count": scope_plan.route_count,
            "matched_route_count": scope_plan.matched_route_count,
            "strict_scope": scope_plan.strict_scope,
            "metadata_filter": bool(metadata_filter),
            "kg_requested": requested_kg_flags.enabled,
            "kg_on_demand_enabled": kg_on_demand_enabled,
        },
        trace_conversation_id=None,
        trace_request_id=_dify_trace_request_id(request.headers, body, request_id=request.state.request_id),
        response_cache_key=None,
        response_cache_ttl_sec=response_cache_ttl_sec,
        response_cache_max_entries=response_cache_max_entries,
        response_cache_enabled=response_cache_enabled,
        singleflight_enabled=singleflight_enabled,
        retrieval_path="rag:primary_scope" if primary_scope_enabled else "rag",
    )


def _dify_response_from_serialized_records(records: list[dict[str, Any]]) -> DifyExternalKnowledgeResponse:
    return DifyExternalKnowledgeResponse(records=[DifyExternalKnowledgeRecord(**record) for record in records])


def _set_main_trace_query(ctx: _DifyExternalRetrievalContext, path: str, *, ok: bool = True) -> None:
    entry = {"kind": "main", "query": ctx.body.query, "path": path, "ok": ok}
    if ctx.trace_queries and ctx.trace_queries[0].get("kind") == "main":
        ctx.trace_queries[0] = entry
        return
    ctx.trace_queries.insert(0, entry)


async def _prepare_dify_response_cache_key(ctx: _DifyExternalRetrievalContext) -> None:
    if not (ctx.response_cache_enabled or ctx.singleflight_enabled):
        return
    cache_token_started = time.perf_counter()
    all_corpus_dataset_ids = [*ctx.dataset_ids, *ctx.metadata_anchor_dataset_ids]
    corpus_token = await run_blocking_call_with_managed_session(
        lambda worker_db: _resolve_dify_response_cache_corpus_token(
            db=worker_db,
            tenant_id=ctx.actor.tenant_id,
            dataset_ids=all_corpus_dataset_ids,
        ),
        request_db=None,
    )
    ctx.stage_timings_ms["response_cache_corpus_token_ms"] = round(
        (time.perf_counter() - cache_token_started) * 1000,
        2,
    )
    if corpus_token:
        ctx.response_cache_key = _build_dify_response_cache_key(
            actor=ctx.actor,
            knowledge_id=ctx.body.knowledge_id,
            query=ctx.body.query,
            retrieval_setting=ctx.body.retrieval_setting,
            metadata_condition=ctx.body.metadata_condition,
            scope_plan=ctx.scope_plan,
            top_k=ctx.top_k,
            candidate_top_k=ctx.candidate_top_k,
            score_threshold=ctx.score_threshold,
            policy_plugin_refs=ctx.policy_plugin_refs,
            corpus_token=corpus_token,
        )


async def _cached_dify_records_for_key(
    cache_key: str,
    *,
    response_cache_enabled: bool,
    ttl_sec: int,
    max_entries: int,
) -> list[dict[str, Any]] | None:
    if not response_cache_enabled:
        return None
    cached_records = _dify_response_cache.get(cache_key, ttl_sec=ttl_sec)
    if cached_records is None:
        cached_records = await _dify_response_cache_redis_payload(cache_key)
        if cached_records is not None:
            _dify_response_cache.set(
                cache_key,
                cached_records,
                ttl_sec=ttl_sec,
                max_entries=max_entries,
            )
    return cached_records


def _log_dify_short_circuit_trace(
    ctx: _DifyExternalRetrievalContext,
    *,
    response_records: list[DifyExternalKnowledgeRecord],
    retrieval_path: str,
    elapsed_ms: float,
    mixed_intent_query_count: int = 0,
) -> None:
    _log_dify_external_rag_trace(
        tenant_id=ctx.actor.tenant_id,
        conversation_id=ctx.trace_conversation_id,
        request_id=ctx.trace_request_id,
        question=ctx.body.query,
        response_records=response_records,
        top_k=ctx.top_k,
        candidate_top_k=ctx.candidate_top_k,
        retrieval_path=retrieval_path,
        elapsed_ms=elapsed_ms,
        metadata_anchor_fallback_count=0,
        mixed_intent_query_count=mixed_intent_query_count,
        retrieval_queries=[{"kind": "main", "query": ctx.body.query, "path": retrieval_path, "ok": True}],
        dify_message_id=ctx.body.dify_message_id,
        dify_workflow_run_id=ctx.body.dify_workflow_run_id,
    )


async def _maybe_return_response_cache_hit(
    ctx: _DifyExternalRetrievalContext,
) -> DifyExternalKnowledgeResponse | None:
    if ctx.response_cache_key is None:
        return None
    cached_records = await _cached_dify_records_for_key(
        ctx.response_cache_key,
        response_cache_enabled=ctx.response_cache_enabled,
        ttl_sec=ctx.response_cache_ttl_sec,
        max_entries=ctx.response_cache_max_entries,
    )
    if cached_records is None:
        return None
    elapsed_ms = round((time.perf_counter() - ctx.started) * 1000, 2)
    response_records = [DifyExternalKnowledgeRecord(**record) for record in cached_records]
    logger.info(
        "Dify external retrieval cache hit client_ip_hash=%s knowledge_id_hash=%s query_hash=%s "
        "top_k=%s candidate_top_k=%s dataset_count=%s records=%s elapsed_ms=%s",
        ctx.log_extra_base["client_ip_hash"],
        ctx.log_extra_base["knowledge_id_hash"],
        ctx.log_extra_base["query_hash"],
        ctx.top_k,
        ctx.candidate_top_k,
        len(ctx.dataset_ids),
        len(response_records),
        elapsed_ms,
        extra={
            **ctx.log_extra_base,
            "phase": "cache_hit",
            "record_count": len(response_records),
            "elapsed_ms": elapsed_ms,
            "response_cache_hit": True,
        },
    )
    return DifyExternalKnowledgeResponse(records=response_records)


async def _maybe_return_singleflight_hit(
    ctx: _DifyExternalRetrievalContext,
) -> DifyExternalKnowledgeResponse | None:
    if not ctx.singleflight_enabled or ctx.response_cache_key is None:
        return None
    ctx.singleflight_key = ctx.response_cache_key
    singleflight_wait_started = time.perf_counter()
    ctx.singleflight_leader, shared_payload, ctx.singleflight_future = await _acquire_or_wait_for_inflight_response(
        ctx.singleflight_key
    )
    if not ctx.singleflight_leader:
        shared_records = shared_payload["records"]
        response_records = [DifyExternalKnowledgeRecord(**record) for record in shared_records]
        elapsed_ms = round((time.perf_counter() - ctx.started) * 1000, 2)
        ctx.stage_timings_ms["singleflight_wait_ms"] = round(
            (time.perf_counter() - singleflight_wait_started) * 1000, 2
        )
        logger.info(
            "Dify external retrieval singleflight hit client_ip_hash=%s knowledge_id_hash=%s "
            "query_hash=%s records=%s elapsed_ms=%s",
            ctx.log_extra_base["client_ip_hash"],
            ctx.log_extra_base["knowledge_id_hash"],
            ctx.log_extra_base["query_hash"],
            len(response_records),
            elapsed_ms,
            extra={
                **ctx.log_extra_base,
                "phase": "singleflight_hit",
                "record_count": len(response_records),
                "elapsed_ms": elapsed_ms,
                "singleflight_hit": True,
                "stage_timings_ms": ctx.stage_timings_ms,
            },
        )
        return DifyExternalKnowledgeResponse(records=response_records)
    return None


async def _maybe_return_leader_cached_response(
    ctx: _DifyExternalRetrievalContext,
) -> DifyExternalKnowledgeResponse | None:
    if not ctx.response_cache_enabled or not ctx.singleflight_key:
        return None
    cached_records = await _cached_dify_records_for_key(
        ctx.singleflight_key,
        response_cache_enabled=True,
        ttl_sec=ctx.response_cache_ttl_sec,
        max_entries=ctx.response_cache_max_entries,
    )
    if cached_records is None:
        return None
    serialized_records = [dict(record) for record in cached_records]
    return _dify_response_from_serialized_records(serialized_records)


def _start_distributed_singleflight_lease_task(ctx: _DifyExternalRetrievalContext) -> None:
    if ctx.distributed_singleflight_lease is None:
        return
    ctx.distributed_singleflight_lease_task = asyncio.create_task(
        _maintain_best_effort_dify_lease(
            ctx.distributed_singleflight_lease,
            ttl_sec=_dify_singleflight_lease_ttl_sec(ctx.response_cache_ttl_sec),
        )
    )


async def _maybe_return_distributed_singleflight_hit(
    ctx: _DifyExternalRetrievalContext,
) -> DifyExternalKnowledgeResponse | None:
    if not ctx.singleflight_key:
        return None
    distributed_wait_started = time.perf_counter()
    (
        distributed_leader,
        distributed_records,
        ctx.distributed_singleflight_lease,
    ) = await _acquire_or_wait_for_distributed_dify_response(
        ctx.singleflight_key,
        response_cache_enabled=ctx.response_cache_enabled,
        response_cache_ttl_sec=ctx.response_cache_ttl_sec,
    )
    ctx.stage_timings_ms["distributed_singleflight_wait_ms"] = round(
        (time.perf_counter() - distributed_wait_started) * 1000,
        2,
    )
    if distributed_leader:
        _start_distributed_singleflight_lease_task(ctx)
        return None
    serialized_records = [dict(record) for record in distributed_records]
    elapsed_ms = round((time.perf_counter() - ctx.started) * 1000, 2)
    response_records = [DifyExternalKnowledgeRecord(**record) for record in serialized_records]
    logger.info(
        "Dify external retrieval distributed cache hit client_ip_hash=%s knowledge_id_hash=%s "
        "query_hash=%s records=%s elapsed_ms=%s",
        ctx.log_extra_base["client_ip_hash"],
        ctx.log_extra_base["knowledge_id_hash"],
        ctx.log_extra_base["query_hash"],
        len(response_records),
        elapsed_ms,
        extra={
            **ctx.log_extra_base,
            "phase": "distributed_cache_hit",
            "record_count": len(response_records),
            "elapsed_ms": elapsed_ms,
            "distributed_singleflight_hit": True,
            "stage_timings_ms": ctx.stage_timings_ms,
        },
    )
    return DifyExternalKnowledgeResponse(records=response_records)


def _dify_cache_source_document_ids(records: list[DifyExternalKnowledgeRecord]) -> list[UUID] | None:
    document_ids: list[UUID] = []
    seen: set[UUID] = set()
    for record in records:
        raw_ids = []
        document_id = record.metadata.get("document_id")
        if document_id is not None:
            raw_ids.append(document_id)
        composite_ids = record.metadata.get("dify_composite_source_document_ids")
        if composite_ids is not None:
            if not isinstance(composite_ids, list):
                logger.info("Dify cache declined reason=invalid_composite_identity records=%s", len(records))
                return None
            raw_ids.extend(composite_ids)
        if not raw_ids:
            logger.info("Dify cache declined reason=missing_document_identity records=%s", len(records))
            return None
        for raw_id in raw_ids:
            parsed = _uuid_or_none(raw_id)
            if parsed is None:
                logger.info("Dify cache declined reason=invalid_document_identity records=%s", len(records))
                return None
            if parsed not in seen:
                seen.add(parsed)
                document_ids.append(parsed)
    return document_ids


async def _maybe_return_cached_or_inflight_dify_response(
    ctx: _DifyExternalRetrievalContext,
) -> DifyExternalKnowledgeResponse | None:
    await _prepare_dify_response_cache_key(ctx)
    for resolver in (
        _maybe_return_response_cache_hit,
        _maybe_return_singleflight_hit,
        _maybe_return_leader_cached_response,
        _maybe_return_distributed_singleflight_hit,
    ):
        response = await resolver(ctx)
        if response is not None:
            document_ids = _dify_cache_source_document_ids(response.records)
            if document_ids is None:
                return None
            if document_ids:
                allowed_ids, missing_ids = await run_blocking_call_with_managed_session(
                    lambda worker_db: get_allowed_document_id_sets(
                        worker_db, ctx.actor.tenant_id, ctx.actor.account_id, document_ids, check_member=False
                    ),
                    request_db=None,
                )
                if missing_ids or set(document_ids) - allowed_ids:
                    logger.info("Dify cache declined reason=document_access_changed records=%s", len(response.records))
                    return None
            from app.services.tenant_quota_service import enforce_tenant_qps_quota_async

            await enforce_tenant_qps_quota_async(tenant_id=ctx.actor.tenant_id, key="retrieval")
            if resolver is _maybe_return_response_cache_hit or resolver is _maybe_return_singleflight_hit:
                _log_dify_short_circuit_trace(
                    ctx,
                    response_records=response.records,
                    retrieval_path="cache_hit" if resolver is _maybe_return_response_cache_hit else "singleflight_hit",
                    elapsed_ms=round((time.perf_counter() - ctx.started) * 1000, 2),
                )
            if ctx.singleflight_key and ctx.singleflight_leader:
                serialized_records = [record.model_dump(mode="json") for record in response.records]
                if resolver is _maybe_return_distributed_singleflight_hit and ctx.response_cache_enabled:
                    _dify_response_cache.set(
                        ctx.singleflight_key,
                        serialized_records,
                        ttl_sec=ctx.response_cache_ttl_sec,
                        max_entries=ctx.response_cache_max_entries,
                    )
                resolve_inflight_response(
                    ctx.singleflight_key, {"records": serialized_records}, expected_future=ctx.singleflight_future
                )
            return response
    return None


async def _run_dify_metadata_anchor_fallback(
    ctx: _DifyExternalRetrievalContext,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    call_kwargs = kwargs
    call_kwargs["account_id"] = ctx.actor.account_id
    fallback_started = time.perf_counter()
    budget_deadline: float | None = None
    if not ctx.fast_latency_profile and ctx.metadata_anchor_total_budget_ms:
        remaining_ms = ctx.metadata_anchor_total_budget_ms - int(ctx.metadata_anchor_budget_spent_ms)
        if remaining_ms <= 0:
            return []
        configured_call_budget = call_kwargs.get("max_elapsed_ms")
        if configured_call_budget is not None and configured_call_budget > 0:
            remaining_ms = min(remaining_ms, configured_call_budget)
        call_kwargs["max_elapsed_ms"] = remaining_ms
        budget_deadline = fallback_started + remaining_ms / 1000
    ctx.db.rollback()
    try:
        return await _run_dify_metadata_anchor_fallback_call(call_kwargs, budget_deadline=budget_deadline)
    finally:
        ctx.metadata_anchor_budget_spent_ms += max(0.0, (time.perf_counter() - fallback_started) * 1000)
        ctx.stage_timings_ms["metadata_anchor_budget_spent_ms"] = round(ctx.metadata_anchor_budget_spent_ms, 2)


async def _run_dify_metadata_anchor_fallback_call(
    call_kwargs: dict[str, Any],
    *,
    budget_deadline: float | None,
) -> list[dict[str, Any]]:
    if budget_deadline is None:
        return await run_blocking_retrieval_call(
            _metadata_anchor_db_fallback_records_with_managed_session,
            budget_deadline=None,
            **call_kwargs,
        )
    remaining_sec = budget_deadline - time.perf_counter()
    if remaining_sec <= 0:
        return []
    try:
        return await asyncio.wait_for(
            run_blocking_retrieval_call(
                _metadata_anchor_db_fallback_records_with_managed_session,
                budget_deadline=budget_deadline,
                **call_kwargs,
            ),
            timeout=remaining_sec,
        )
    except TimeoutError:
        logger.info(
            "Dify metadata anchor fallback exceeded request budget query_hash=%s",
            _diagnostic_query_hash(call_kwargs["query"]),
        )
        return []


def _dify_metadata_anchor_preflight_enabled(ctx: _DifyExternalRetrievalContext) -> bool:
    return bool(
        settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED
        and ctx.metadata_anchor_db_fallback_enabled
        and (
            not ctx.fast_latency_profile
            or _query_has_specific_fast_metadata_anchor_candidate(
                ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs
            )
        )
        and not ctx.metadata_filter
        and _query_allows_metadata_anchor_preflight(
            ctx.body.query,
            query_prefers_question_anchor=ctx.query_prefers_question_anchor,
            query_prefers_service_anchor=ctx.query_prefers_service_anchor,
            policy_plugin_refs=ctx.policy_plugin_refs,
        )
    )


async def _apply_metadata_anchor_preflight(ctx: _DifyExternalRetrievalContext) -> None:
    if not _dify_metadata_anchor_preflight_enabled(ctx):
        return
    preflight_started = time.perf_counter()
    metadata_anchor_records = await _run_dify_metadata_anchor_fallback(
        ctx,
        tenant_id=ctx.actor.tenant_id,
        dataset_ids=ctx.metadata_anchor_dataset_ids,
        query=ctx.body.query,
        top_k=ctx.top_k,
        policy_plugin_refs=ctx.policy_plugin_refs,
        existing_records=[],
        metadata_filter=ctx.metadata_filter,
        statement_timeout_ms_override=(
            settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_STATEMENT_TIMEOUT_MS
            if ctx.fast_latency_profile
            else None
        ),
        max_elapsed_ms=(
            settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_MAX_ELAPSED_MS
            if ctx.fast_latency_profile
            else None
        ),
    )
    metadata_anchor_records = _filtered_metadata_preflight_records(ctx, metadata_anchor_records)
    has_preflight_anchor = _dify_preflight_has_anchor(ctx, metadata_anchor_records)
    ctx.stage_timings_ms["metadata_preflight_ms"] = round((time.perf_counter() - preflight_started) * 1000, 2)
    ctx.stage_timings_ms["metadata_preflight_records"] = len(metadata_anchor_records)
    ctx.stage_timings_ms["metadata_preflight_accepted"] = has_preflight_anchor
    if has_preflight_anchor:
        ctx.metadata_anchor_fallback_count = len(metadata_anchor_records)
        ctx.records.extend(metadata_anchor_records)
        ctx.retrieval_path = "metadata_anchor:preflight"
        _set_main_trace_query(ctx, ctx.retrieval_path)


def _filtered_metadata_preflight_records(
    ctx: _DifyExternalRetrievalContext,
    metadata_anchor_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if ctx.query_prefers_service_anchor and _query_has_quoted_anchor_candidate(ctx.body.query):
        metadata_anchor_records = [
            record
            for record in metadata_anchor_records
            if _record_matches_quoted_query_anchor_for_policy(
                record,
                query=ctx.body.query,
                policy_plugin_refs=ctx.policy_plugin_refs,
            )
        ]
    if _query_has_mixed_intent_for_policy(
        ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs
    ) and _query_has_quoted_anchor_candidate(ctx.body.query):
        metadata_anchor_records = _compact_mixed_intent_exact_anchor_records(
            metadata_anchor_records,
            query=ctx.body.query,
            top_k=ctx.top_k,
            policy_plugin_refs=ctx.policy_plugin_refs,
        )
    return metadata_anchor_records


def _dify_preflight_has_anchor(
    ctx: _DifyExternalRetrievalContext,
    metadata_anchor_records: list[dict[str, Any]],
) -> bool:
    if ctx.query_prefers_service_anchor:
        return _records_have_confident_metadata_anchor(
            metadata_anchor_records,
            query=ctx.body.query,
            policy_plugin_refs=ctx.policy_plugin_refs,
        )
    return _records_have_strong_question_anchor(
        metadata_anchor_records,
        query=ctx.body.query,
        policy_plugin_refs=ctx.policy_plugin_refs,
    )


def _dify_mixed_intent_preflight_enabled(ctx: _DifyExternalRetrievalContext) -> bool:
    return bool(
        not ctx.records
        and not ctx.fast_latency_profile
        and settings.DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED
        and ctx.metadata_anchor_db_fallback_enabled
        and _query_has_mixed_intent_for_policy(ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs)
        and not _query_has_quoted_anchor_candidate(ctx.body.query)
    )


async def _apply_mixed_intent_preflight(ctx: _DifyExternalRetrievalContext) -> None:
    if not _dify_mixed_intent_preflight_enabled(ctx):
        return
    mixed_intent_queries = _mixed_intent_retrieval_queries(ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs)
    mixed_preflight_records: list[dict[str, Any]] = []
    mixed_preflight_query_count = 0
    mixed_preflight_trace_queries: list[dict[str, Any]] = []
    mixed_intent_subquery_top_k = _resolve_mixed_intent_subquery_top_k(
        response_top_k=ctx.top_k,
        candidate_top_k=ctx.candidate_top_k,
    )
    for subquery in mixed_intent_queries:
        if not _subquery_allows_metadata_anchor_preflight(subquery, policy_plugin_refs=ctx.policy_plugin_refs):
            return
        subquery_anchor_records = await _run_dify_metadata_anchor_fallback(
            ctx,
            tenant_id=ctx.actor.tenant_id,
            dataset_ids=ctx.metadata_anchor_dataset_ids,
            query=subquery,
            top_k=mixed_intent_subquery_top_k,
            policy_plugin_refs=ctx.policy_plugin_refs,
            existing_records=[],
            metadata_filter=ctx.metadata_filter,
            prefer_question_anchor_first=True,
        )
        subquery_anchor_records = _filter_records_by_mixed_intent_subject_anchor(
            subquery_anchor_records,
            subquery=subquery,
            policy_plugin_refs=ctx.policy_plugin_refs,
        )
        if not subquery_anchor_records:
            return
        mixed_preflight_query_count += 1
        mixed_preflight_trace_queries.append(
            {"kind": "subq", "query": subquery, "path": "metadata_anchor:mixed_preflight_subquery", "ok": True}
        )
        mixed_preflight_records.extend(_tag_mixed_intent_records(subquery_anchor_records, subquery=subquery))
    if mixed_preflight_records:
        ctx.mixed_intent_query_count += mixed_preflight_query_count
        ctx.metadata_anchor_fallback_count += len(mixed_preflight_records)
        ctx.records.extend(mixed_preflight_records)
        ctx.retrieval_path = "metadata_anchor:mixed_preflight"
        _set_main_trace_query(ctx, ctx.retrieval_path)
        ctx.trace_queries.extend(mixed_preflight_trace_queries)


def _subquery_allows_metadata_anchor_preflight(
    subquery: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    return _query_allows_metadata_anchor_preflight(
        subquery,
        query_prefers_question_anchor=_query_prefers_question_anchor(subquery, policy_plugin_refs=policy_plugin_refs),
        query_prefers_service_anchor=_query_prefers_service_anchor(subquery, policy_plugin_refs=policy_plugin_refs),
        policy_plugin_refs=policy_plugin_refs,
    )


async def _retrieve_primary_records(ctx: _DifyExternalRetrievalContext) -> None:
    primary_retrieve_started = time.perf_counter()
    primary_citations = await _retrieve_dataset_citations(
        db=ctx.db,
        tenant_id=ctx.actor.tenant_id,
        account_id=ctx.actor.account_id,
        dataset_ids=ctx.primary_dataset_ids,
        query=ctx.body.query,
        top_k=ctx.candidate_top_k,
        requested_top_k=ctx.top_k,
        score_threshold=ctx.score_threshold,
        metadata_filter=ctx.metadata_filter,
        enable_kg_query_expansion=ctx.primary_kg_flags.enable_query_expansion,
        enable_kg_chunk_injection=ctx.primary_kg_flags.enable_chunk_injection,
        kg_chunk_injection_max_chunks=ctx.primary_kg_flags.chunk_injection_max_chunks,
        enable_kg_chunk_boost=ctx.primary_kg_flags.enable_chunk_boost,
        kg_chunk_boost_weight=ctx.primary_kg_flags.chunk_boost_weight,
        kg_chunk_boost_max_promoted=ctx.primary_kg_flags.chunk_boost_max_promoted,
        enable_reranker=ctx.external_reranker_enabled,
        retrieval_mode="vector" if ctx.fast_latency_profile else "hybrid",
    )
    ctx.stage_timings_ms["primary_retrieve_ms"] = round((time.perf_counter() - primary_retrieve_started) * 1000, 2)
    ctx.primary_citation_count = len(primary_citations)
    _set_main_trace_query(ctx, ctx.retrieval_path, ok=bool(primary_citations))
    records_started = time.perf_counter()
    ctx.records.extend(
        await _records_from_citations_with_managed_hydration(
            db=ctx.db,
            tenant_id=ctx.actor.tenant_id,
            citations=primary_citations,
            fallback_dataset_id=ctx.primary_dataset_ids[0] if ctx.primary_dataset_ids else None,
            query=ctx.body.query,
            policy_plugin_refs=ctx.policy_plugin_refs,
        )
    )
    ctx.stage_timings_ms["primary_records_from_citations_ms"] = round((time.perf_counter() - records_started) * 1000, 2)


async def _apply_mixed_intent_supplement(ctx: _DifyExternalRetrievalContext) -> None:
    mixed_intent_supplement_skipped = _records_have_exact_anchor_full_answer(
        ctx.records,
        query=ctx.body.query,
        policy_plugin_refs=ctx.policy_plugin_refs,
    )
    if mixed_intent_supplement_skipped:
        ctx.retrieval_path = f"{ctx.retrieval_path}:mixed_intent_skip_exact_anchor"
    if (
        ctx.fast_latency_profile
        or not settings.DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED
        or mixed_intent_supplement_skipped
    ):
        return
    mixed_intent_queries = _mixed_intent_retrieval_queries(ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs)
    mixed_intent_subquery_top_k = _resolve_mixed_intent_subquery_top_k(
        response_top_k=ctx.top_k,
        candidate_top_k=ctx.candidate_top_k,
    )
    for subquery in mixed_intent_queries:
        await _append_mixed_intent_subquery_records(
            ctx, subquery, mixed_intent_subquery_top_k=mixed_intent_subquery_top_k
        )
    if ctx.mixed_intent_query_count:
        ctx.retrieval_path = f"{ctx.retrieval_path}:mixed_intent"


async def _append_mixed_intent_subquery_records(
    ctx: _DifyExternalRetrievalContext,
    subquery: str,
    *,
    mixed_intent_subquery_top_k: int,
) -> None:
    subquery_anchor_records: list[dict[str, Any]] = []
    if ctx.metadata_anchor_db_fallback_enabled and _subquery_allows_metadata_anchor_preflight(
        subquery, policy_plugin_refs=ctx.policy_plugin_refs
    ):
        subquery_anchor_records = await _run_dify_metadata_anchor_fallback(
            ctx,
            tenant_id=ctx.actor.tenant_id,
            dataset_ids=ctx.primary_dataset_ids,
            query=subquery,
            top_k=mixed_intent_subquery_top_k,
            policy_plugin_refs=ctx.policy_plugin_refs,
            existing_records=[],
            metadata_filter=ctx.metadata_filter,
            prefer_question_anchor_first=not _query_has_quoted_anchor_candidate(ctx.body.query),
        )
        subquery_anchor_records = _filter_records_by_mixed_intent_subject_anchor(
            subquery_anchor_records,
            subquery=subquery,
            policy_plugin_refs=ctx.policy_plugin_refs,
        )
    if subquery_anchor_records:
        ctx.mixed_intent_query_count += 1
        ctx.metadata_anchor_fallback_count += len(subquery_anchor_records)
        ctx.trace_queries.append(
            {"kind": "subq", "query": subquery, "path": "metadata_anchor:mixed_intent_subquery", "ok": True}
        )
        ctx.records.extend(_tag_mixed_intent_records(subquery_anchor_records, subquery=subquery))
        return
    subquery_citations = await _retrieve_dataset_citations(
        db=ctx.db,
        tenant_id=ctx.actor.tenant_id,
        account_id=ctx.actor.account_id,
        dataset_ids=ctx.primary_dataset_ids,
        query=subquery,
        top_k=mixed_intent_subquery_top_k,
        requested_top_k=mixed_intent_subquery_top_k,
        score_threshold=ctx.score_threshold,
        metadata_filter=ctx.metadata_filter,
        enable_kg_query_expansion=ctx.primary_kg_flags.enable_query_expansion,
        enable_kg_chunk_injection=ctx.primary_kg_flags.enable_chunk_injection,
        kg_chunk_injection_max_chunks=ctx.primary_kg_flags.chunk_injection_max_chunks,
        enable_kg_chunk_boost=ctx.primary_kg_flags.enable_chunk_boost,
        kg_chunk_boost_weight=ctx.primary_kg_flags.chunk_boost_weight,
        kg_chunk_boost_max_promoted=ctx.primary_kg_flags.chunk_boost_max_promoted,
        enable_reranker=False,
    )
    ctx.trace_queries.append(
        {"kind": "subq", "query": subquery, "path": "rag:mixed_intent_subquery", "ok": bool(subquery_citations)}
    )
    ctx.mixed_intent_query_count += 1
    ctx.mixed_intent_citation_count += len(subquery_citations)
    subquery_records = await _records_from_citations_with_managed_hydration(
        db=ctx.db,
        tenant_id=ctx.actor.tenant_id,
        citations=subquery_citations,
        fallback_dataset_id=ctx.primary_dataset_ids[0] if ctx.primary_dataset_ids else None,
        query=subquery,
        hydration_query=ctx.body.query,
        policy_plugin_refs=ctx.policy_plugin_refs,
    )
    ctx.records.extend(_tag_mixed_intent_records(subquery_records, subquery=subquery))


async def _apply_kg_on_demand(ctx: _DifyExternalRetrievalContext) -> None:
    if not (ctx.requested_kg_flags.enabled and ctx.kg_on_demand_enabled):
        return
    if _records_can_skip_kg_on_demand(ctx.records, query=ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs):
        ctx.kg_on_demand_skipped = True
        ctx.retrieval_path = f"{ctx.retrieval_path}:kg_on_demand_skip"
        return
    kg_records = await _dify_kg_on_demand_records(
        db=ctx.db,
        tenant_id=ctx.actor.tenant_id,
        account_id=ctx.actor.account_id,
        dataset_ids=ctx.primary_dataset_ids,
        query=ctx.body.query,
        requested_kg_flags=ctx.requested_kg_flags,
        policy_plugin_refs=ctx.policy_plugin_refs,
    )
    if kg_records:
        ctx.kg_on_demand_triggered = True
        ctx.retrieval_path = f"{ctx.retrieval_path}:kg_on_demand"
        ctx.records.extend(kg_records)
        return
    ctx.kg_on_demand_skipped = True
    ctx.retrieval_path = f"{ctx.retrieval_path}:kg_on_demand_empty"


async def _apply_expansion_scope(ctx: _DifyExternalRetrievalContext) -> None:
    if ctx.fast_latency_profile or not ctx.expansion_dataset_ids:
        return
    if _records_meet_primary_scope(ctx.records, query=ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs):
        return
    ctx.retrieval_path = "rag:primary_scope+expansion_scope"
    expansion_citations = await _retrieve_dataset_citations(
        db=ctx.db,
        tenant_id=ctx.actor.tenant_id,
        account_id=ctx.actor.account_id,
        dataset_ids=ctx.expansion_dataset_ids,
        query=ctx.body.query,
        top_k=ctx.candidate_top_k,
        requested_top_k=ctx.top_k,
        score_threshold=ctx.score_threshold,
        metadata_filter=ctx.metadata_filter,
        enable_kg_query_expansion=ctx.requested_kg_flags.enable_query_expansion,
        enable_kg_chunk_injection=ctx.requested_kg_flags.enable_chunk_injection,
        kg_chunk_injection_max_chunks=ctx.requested_kg_flags.chunk_injection_max_chunks,
        enable_kg_chunk_boost=ctx.requested_kg_flags.enable_chunk_boost,
        kg_chunk_boost_weight=ctx.requested_kg_flags.chunk_boost_weight,
        kg_chunk_boost_max_promoted=ctx.requested_kg_flags.chunk_boost_max_promoted,
        enable_reranker=ctx.external_reranker_enabled,
    )
    ctx.expansion_citation_count = len(expansion_citations)
    ctx.records.extend(
        await _records_from_citations_with_managed_hydration(
            db=ctx.db,
            tenant_id=ctx.actor.tenant_id,
            citations=expansion_citations,
            fallback_dataset_id=ctx.expansion_dataset_ids[0] if ctx.expansion_dataset_ids else None,
            query=ctx.body.query,
            policy_plugin_refs=ctx.policy_plugin_refs,
        )
    )


async def _apply_metadata_anchor_fallback_to_records(ctx: _DifyExternalRetrievalContext) -> None:
    if ctx.fast_latency_profile:
        return
    if _records_can_skip_metadata_anchor_fallback(
        ctx.records, query=ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs
    ):
        return
    metadata_anchor_records = await _run_dify_metadata_anchor_fallback(
        ctx,
        tenant_id=ctx.actor.tenant_id,
        dataset_ids=ctx.metadata_anchor_dataset_ids,
        query=ctx.body.query,
        top_k=ctx.top_k,
        policy_plugin_refs=ctx.policy_plugin_refs,
        existing_records=ctx.records,
        metadata_filter=ctx.metadata_filter,
    )
    if metadata_anchor_records:
        ctx.metadata_anchor_fallback_count = len(metadata_anchor_records)
        ctx.records.extend(metadata_anchor_records)
        ctx.retrieval_path = f"{ctx.retrieval_path}+metadata_anchor"


async def _execute_dify_external_retrieval(ctx: _DifyExternalRetrievalContext) -> None:
    ctx.query_prefers_question_anchor = _query_prefers_question_anchor(
        ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs
    )
    ctx.query_prefers_service_anchor = _query_prefers_service_anchor(
        ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs
    )
    ctx.metadata_anchor_db_fallback_enabled = settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED
    ctx.metadata_anchor_total_budget_ms = max(
        0,
        settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS,
    )
    await _apply_metadata_anchor_preflight(ctx)
    await _apply_mixed_intent_preflight(ctx)
    if ctx.records:
        from app.services.tenant_quota_service import enforce_tenant_qps_quota_async

        await enforce_tenant_qps_quota_async(tenant_id=ctx.actor.tenant_id, key="retrieval")
        return
    await _retrieve_primary_records(ctx)
    await _apply_mixed_intent_supplement(ctx)
    await _apply_kg_on_demand(ctx)
    await _apply_expansion_scope(ctx)
    await _apply_metadata_anchor_fallback_to_records(ctx)


async def _finalize_dify_external_retrieval(ctx: _DifyExternalRetrievalContext) -> DifyExternalKnowledgeResponse:
    ctx.citation_count = ctx.primary_citation_count + ctx.expansion_citation_count + ctx.mixed_intent_citation_count
    postprocess_started = time.perf_counter()
    ctx.records = _dedupe_records(ctx.records, query=ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs)
    _sort_records_for_query(ctx.records, query=ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs)
    if ctx.external_reranker_enabled:
        ctx.db.rollback()
        ctx.records = await _final_rerank_records_for_query(
            ctx.records,
            query=ctx.body.query,
            top_k=ctx.top_k,
            policy_plugin_refs=ctx.policy_plugin_refs,
        )
    policy_diagnostics = _records_retrieval_policy_diagnostics(
        ctx.records,
        query=ctx.body.query,
        policy_plugin_refs=ctx.policy_plugin_refs,
    )
    compacted_records = _compact_records_for_response(
        ctx.records,
        query=ctx.body.query,
        top_k=ctx.response_top_k,
        policy_plugin_refs=ctx.policy_plugin_refs,
    )
    if ctx.fast_latency_profile:
        compacted_records = _compact_fast_records_for_response(
            compacted_records,
            query=ctx.body.query,
            top_k=ctx.response_top_k,
            policy_plugin_refs=ctx.policy_plugin_refs,
        )
    response_records = [DifyExternalKnowledgeRecord(**record) for record in compacted_records]
    ctx.stage_timings_ms["postprocess_ms"] = round((time.perf_counter() - postprocess_started) * 1000, 2)
    serialized_response_records = [record.model_dump(mode="json") for record in response_records]
    if ctx.singleflight_key and ctx.singleflight_leader:
        resolve_inflight_response(
            ctx.singleflight_key, {"records": serialized_response_records}, expected_future=ctx.singleflight_future
        )
    if _dify_cache_source_document_ids(response_records) is not None:
        if ctx.response_cache_enabled and ctx.response_cache_key is not None:
            _dify_response_cache.set(
                ctx.response_cache_key,
                serialized_response_records,
                ttl_sec=ctx.response_cache_ttl_sec,
                max_entries=ctx.response_cache_max_entries,
            )
            await _set_dify_response_cache_redis_payload(
                ctx.response_cache_key,
                serialized_response_records,
                ttl_sec=ctx.response_cache_ttl_sec,
            )
        if ctx.singleflight_key and ctx.distributed_singleflight_lease is not None and not ctx.response_cache_enabled:
            await _set_dify_response_cache_redis_payload(
                _dify_singleflight_result_key(ctx.singleflight_key),
                serialized_response_records,
                ttl_sec=_DIFY_RESPONSE_SINGLEFLIGHT_RESULT_TTL_SEC,
            )
    elapsed_ms = round((time.perf_counter() - ctx.started) * 1000, 2)
    record_count = len(response_records)
    logger.info(
        "Dify external retrieval completed client_ip_hash=%s knowledge_id_hash=%s query_hash=%s "
        "top_k=%s candidate_top_k=%s score_threshold=%s dataset_count=%s "
        "primary_dataset_count=%s expansion_dataset_count=%s citations=%s primary_citations=%s "
        "expansion_citations=%s candidate_records=%s records=%s elapsed_ms=%s metadata_filter=%s "
        "retrieval_path=%s metadata_anchor_fallback_records=%s policy_records=%s "
        "policy_boosted_records=%s policy_boost_field_records=%s "
        "policy_query_expansion_records=%s policy_rerank_feature_records=%s "
        "policy_anchor_mismatch_records=%s stage_timings=%s",
        ctx.log_extra_base["client_ip_hash"],
        ctx.log_extra_base["knowledge_id_hash"],
        ctx.log_extra_base["query_hash"],
        ctx.top_k,
        ctx.candidate_top_k,
        ctx.score_threshold,
        len(ctx.dataset_ids),
        len(ctx.primary_dataset_ids),
        len(ctx.expansion_dataset_ids),
        ctx.citation_count,
        ctx.primary_citation_count,
        ctx.expansion_citation_count,
        len(ctx.records),
        record_count,
        elapsed_ms,
        bool(ctx.metadata_filter),
        ctx.retrieval_path,
        ctx.metadata_anchor_fallback_count,
        policy_diagnostics["retrieval_policy_record_count"],
        policy_diagnostics["retrieval_policy_boosted_record_count"],
        policy_diagnostics["retrieval_policy_boost_field_record_count"],
        policy_diagnostics["retrieval_policy_query_expansion_record_count"],
        policy_diagnostics["retrieval_policy_rerank_feature_record_count"],
        policy_diagnostics["retrieval_policy_anchor_mismatch_record_count"],
        ctx.stage_timings_ms,
        extra={
            **ctx.log_extra_base,
            "phase": "finished",
            "citation_count": ctx.citation_count,
            "primary_citation_count": ctx.primary_citation_count,
            "expansion_citation_count": ctx.expansion_citation_count,
            "mixed_intent_query_count": ctx.mixed_intent_query_count,
            "mixed_intent_citation_count": ctx.mixed_intent_citation_count,
            "candidate_record_count": len(ctx.records),
            "record_count": record_count,
            "elapsed_ms": elapsed_ms,
            "retrieval_path": ctx.retrieval_path,
            "metadata_anchor_fallback_count": ctx.metadata_anchor_fallback_count,
            "kg_on_demand_triggered": ctx.kg_on_demand_triggered,
            "kg_on_demand_skipped": ctx.kg_on_demand_skipped,
            **policy_diagnostics,
        },
    )
    _log_dify_external_rag_trace(
        tenant_id=ctx.actor.tenant_id,
        conversation_id=ctx.trace_conversation_id,
        request_id=ctx.trace_request_id,
        question=ctx.body.query,
        response_records=response_records,
        top_k=ctx.top_k,
        candidate_top_k=ctx.candidate_top_k,
        retrieval_path=ctx.retrieval_path,
        elapsed_ms=elapsed_ms,
        metadata_anchor_fallback_count=ctx.metadata_anchor_fallback_count,
        mixed_intent_query_count=ctx.mixed_intent_query_count,
        retrieval_queries=ctx.trace_queries,
        dify_message_id=ctx.body.dify_message_id,
        dify_workflow_run_id=ctx.body.dify_workflow_run_id,
    )
    return DifyExternalKnowledgeResponse(records=response_records)


def _reject_dify_inflight_response(ctx: _DifyExternalRetrievalContext, exc: Exception) -> None:
    if ctx.singleflight_key and ctx.singleflight_leader:
        reject_inflight_response(ctx.singleflight_key, exc, expected_future=ctx.singleflight_future)


def _log_dify_external_retrieval_failure(ctx: _DifyExternalRetrievalContext) -> None:
    elapsed_ms = round((time.perf_counter() - ctx.started) * 1000, 2)
    policy_diagnostics = _records_retrieval_policy_diagnostics(
        ctx.records,
        query=ctx.body.query,
        policy_plugin_refs=ctx.policy_plugin_refs,
    )
    logger.exception(
        "Dify external retrieval failed client_ip_hash=%s knowledge_id_hash=%s query_hash=%s "
        "top_k=%s candidate_top_k=%s score_threshold=%s dataset_count=%s "
        "primary_dataset_count=%s expansion_dataset_count=%s citations=%s records=%s elapsed_ms=%s "
        "metadata_filter=%s retrieval_path=%s metadata_anchor_fallback_records=%s "
        "policy_records=%s policy_boosted_records=%s "
        "policy_boost_field_records=%s policy_query_expansion_records=%s "
        "policy_rerank_feature_records=%s policy_anchor_mismatch_records=%s",
        ctx.log_extra_base["client_ip_hash"],
        ctx.log_extra_base["knowledge_id_hash"],
        ctx.log_extra_base["query_hash"],
        ctx.top_k,
        ctx.candidate_top_k,
        ctx.score_threshold,
        len(ctx.dataset_ids),
        len(ctx.primary_dataset_ids),
        len(ctx.expansion_dataset_ids),
        ctx.citation_count,
        len(ctx.records),
        elapsed_ms,
        bool(ctx.metadata_filter),
        ctx.retrieval_path,
        ctx.metadata_anchor_fallback_count,
        policy_diagnostics["retrieval_policy_record_count"],
        policy_diagnostics["retrieval_policy_boosted_record_count"],
        policy_diagnostics["retrieval_policy_boost_field_record_count"],
        policy_diagnostics["retrieval_policy_query_expansion_record_count"],
        policy_diagnostics["retrieval_policy_rerank_feature_record_count"],
        policy_diagnostics["retrieval_policy_anchor_mismatch_record_count"],
        extra={
            **ctx.log_extra_base,
            "phase": "failed",
            "citation_count": ctx.citation_count,
            "mixed_intent_query_count": ctx.mixed_intent_query_count,
            "mixed_intent_citation_count": ctx.mixed_intent_citation_count,
            "record_count": len(ctx.records),
            "elapsed_ms": elapsed_ms,
            "retrieval_path": ctx.retrieval_path,
            "metadata_anchor_fallback_count": ctx.metadata_anchor_fallback_count,
            "kg_on_demand_triggered": ctx.kg_on_demand_triggered,
            "kg_on_demand_skipped": ctx.kg_on_demand_skipped,
            **policy_diagnostics,
        },
    )


async def _retrieve_external_knowledge(
    *,
    request: Request,
    body: DifyExternalKnowledgeRequest,
    actor: _DifyActor,
    db: Session,
) -> DifyExternalKnowledgeResponse:
    ctx = _build_dify_external_retrieval_context(
        request=request,
        body=body,
        actor=actor,
        db=db,
    )
    try:
        all_retrieval_dataset_ids = [*ctx.dataset_ids, *ctx.metadata_anchor_dataset_ids]
        await run_blocking_call_with_managed_session(
            lambda worker_db: get_readable_datasets_map(
                worker_db, ctx.actor.tenant_id, ctx.actor.account_id, all_retrieval_dataset_ids
            ),
            request_db=None,
        )
        ctx.trace_conversation_id = await run_blocking_call_with_managed_session(
            lambda worker_db: _dify_trace_conversation_id(
                request,
                body,
                db=worker_db,
                tenant_id=actor.tenant_id,
                account_id=actor.account_id,
            ),
            request_db=None,
        )
        cached_response = await _maybe_return_cached_or_inflight_dify_response(ctx)
        if cached_response is not None:
            return cached_response
        await _execute_dify_external_retrieval(ctx)
        return await _finalize_dify_external_retrieval(ctx)
    except asyncio.CancelledError:
        _reject_dify_inflight_response(
            ctx,
            InflightResponseLeaderCancelledError("singleflight leader request cancelled"),
        )
        raise
    except HTTPException as exc:
        _reject_dify_inflight_response(ctx, exc)
        raise
    except Exception as exc:
        _reject_dify_inflight_response(ctx, exc)
        _log_dify_external_retrieval_failure(ctx)
        raise
    finally:
        await _cleanup_distributed_dify_response_lease(
            ctx.distributed_singleflight_lease_task, ctx.distributed_singleflight_lease
        )
