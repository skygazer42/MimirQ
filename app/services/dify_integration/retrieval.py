"""Dify retrieval operations."""

import asyncio
import contextlib
import time
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.retrieval.planner import DatasetScopePlan
from app.services.dify_integration import (
    citation_records,
    common,
    compaction,
    conversation_turns,
    evidence_adapter,
    kg_on_demand,
    knowledge_scope,
    metadata_anchor,
    metadata_condition_helpers,
    policy_helpers,
    query_policy,
    record_processing,
    record_ranking,
    request_preferences,
    response_cache,
    scoring,
    tracing,
)
from app.services.dify_integration import records as record_values
from app.types.dify_integration import DifyActor as _DifyActor
from app.types.dify_integration import (
    DifyExternalKnowledgeRecord,
    DifyExternalKnowledgeRequest,
    DifyExternalKnowledgeResponse,
)
from app.types.dify_integration import DifyKGFlags as _DifyKGFlags

logger = get_logger(__name__)


def _metadata_condition_to_filter(
    condition: dict[str, Any] | None,
    *,
    allowed_fields: set[str] | None = None,
) -> dict[str, Any] | None:
    try:
        return metadata_condition_helpers.metadata_condition_to_filter(
            condition,
            allowed_fields=allowed_fields,
        )
    except metadata_condition_helpers.MetadataConditionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_metadata_filter_fields(metadata_filter: dict[str, Any], *, allowed_fields: set[str] | None) -> None:
    try:
        metadata_condition_helpers.validate_metadata_filter_fields(
            metadata_filter,
            allowed_fields=allowed_fields,
        )
    except metadata_condition_helpers.MetadataConditionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _dify_metadata_condition_item_to_filter(condition: dict[str, Any]) -> dict[str, Any]:
    try:
        return metadata_condition_helpers.dify_metadata_condition_item_to_filter(condition)
    except metadata_condition_helpers.MetadataConditionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@dataclass
class _DifyExternalRetrievalContext:
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
    trace_conversation_id: Any
    trace_request_id: Any
    response_cache_key: str | None
    cache_policy: response_cache.ResponseCachePolicy

    stage_timings_ms: dict[str, Any] = dataclass_field(default_factory=dict)

    records: list[dict[str, Any]] = dataclass_field(default_factory=list)
    finalized_records: record_processing.FinalizedRecords = dataclass_field(init=False, repr=False)
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


def _build_dify_external_retrieval_context(
    *,
    request_headers: Mapping[str, str],
    request_id: str | None,
    client_ip: str | None,
    body: DifyExternalKnowledgeRequest,
    actor: _DifyActor,
    db: Session,
) -> _DifyExternalRetrievalContext:
    started = time.perf_counter()
    scope_plan = knowledge_scope.resolve_scope(body.knowledge_id, query=body.query)
    dataset_ids = list(scope_plan.dataset_ids)
    primary_scope_enabled = settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED
    primary_dataset_ids = _primary_scope_dataset_ids(scope_plan, primary_scope_enabled=primary_scope_enabled)
    expansion_dataset_ids = list(scope_plan.expansion_dataset_ids if primary_scope_enabled else ())
    configured_max = settings.DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX or 5
    top_k = max(1, min(int(body.retrieval_setting.top_k), configured_max))
    latency_profile = request_preferences._resolve_dify_latency_profile(body.retrieval_setting)
    fast_latency_profile = latency_profile == "fast"
    candidate_top_k = (
        compaction._dify_fast_candidate_top_k(top_k)
        if fast_latency_profile
        else request_preferences._resolve_internal_candidate_top_k(top_k)
    )
    response_top_k = compaction._dify_fast_response_top_k(top_k) if fast_latency_profile else top_k
    policy_fallback_multiplier = 1
    if not fast_latency_profile:
        policy_fallback_multiplier = knowledge_scope.resolve_policy_fallback_multiplier(body.knowledge_id)
        candidate_top_k = policy_helpers.apply_policy_fallback_candidate_multiplier(
            candidate_top_k,
            multiplier=policy_fallback_multiplier,
        )
    policy_plugin_refs = knowledge_scope.resolve_policy_plugin_refs(body.knowledge_id)
    if (
        not fast_latency_profile
        and query_policy._query_has_mixed_intent_for_policy(body.query, policy_plugin_refs=policy_plugin_refs)
        and scoring._dify_external_reranker_enabled()
    ):
        candidate_top_k = min(candidate_top_k, top_k)
    score_threshold = common._clamp_score(body.retrieval_setting.score_threshold)
    metadata_filter = _metadata_condition_to_filter(
        body.metadata_condition,
        allowed_fields=knowledge_scope.resolve_policy_filter_fields(body.knowledge_id),
    )
    requested_kg_flags = request_preferences._resolve_dify_kg_flags(body.retrieval_setting)
    kg_on_demand_enabled = False if fast_latency_profile else settings.DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_ENABLED
    primary_kg_flags = (
        request_preferences._disabled_dify_kg_flags()
        if fast_latency_profile
        else (
            request_preferences._disabled_dify_kg_flags()
            if requested_kg_flags.enabled and kg_on_demand_enabled
            else requested_kg_flags
        )
    )
    cache_policy = response_cache.resolve_policy()
    return _DifyExternalRetrievalContext(
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
        external_reranker_enabled=False if fast_latency_profile else scoring._dify_external_reranker_enabled(),
        score_threshold=score_threshold,
        metadata_filter=metadata_filter,
        metadata_anchor_dataset_ids=knowledge_scope.extend_sibling_policy_scope(
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
            "client_ip_hash": common._diagnostic_value_hash(client_ip),
            "knowledge_id_hash": common._diagnostic_value_hash(body.knowledge_id),
            "query_hash": scoring._diagnostic_query_hash(body.query),
            "knowledge_id_chars": len(str(body.knowledge_id or "")),
            "query_chars": len(str(body.query or "")),
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
        trace_conversation_id=conversation_turns.resolve_trace_conversation_id(
            body=body,
            request_headers=request_headers,
            db=db,
            tenant_id=actor.tenant_id,
            account_id=actor.account_id,
        ),
        trace_request_id=tracing._dify_trace_request_id(request_headers, body, request_id=request_id),
        response_cache_key=None,
        cache_policy=cache_policy,
        retrieval_path="rag:primary_scope" if primary_scope_enabled else "rag",
    )


def _set_main_trace_query(ctx: _DifyExternalRetrievalContext, path: str, *, ok: bool = True) -> None:
    entry = {"kind": "main", "query": ctx.body.query, "path": path, "ok": ok}
    if ctx.trace_queries and str(ctx.trace_queries[0].get("kind") or "") == "main":
        ctx.trace_queries[0] = entry
        return
    ctx.trace_queries.insert(0, entry)


async def _prepare_dify_response_cache_key(ctx: _DifyExternalRetrievalContext) -> None:
    prepared = response_cache.prepare_key(
        db=ctx.db,
        actor=ctx.actor,
        body=ctx.body,
        scope_plan=ctx.scope_plan,
        top_k=ctx.top_k,
        candidate_top_k=ctx.candidate_top_k,
        score_threshold=ctx.score_threshold,
        policy_plugin_refs=ctx.policy_plugin_refs,
        policy=ctx.cache_policy,
    )
    ctx.response_cache_key = prepared.key
    ctx.stage_timings_ms.update(prepared.timings_ms)


def _log_dify_short_circuit_trace(
    ctx: _DifyExternalRetrievalContext,
    *,
    response_records: list[DifyExternalKnowledgeRecord],
    retrieval_path: str,
    elapsed_ms: float,
    mixed_intent_query_count: int = 0,
) -> None:
    tracing._log_dify_external_rag_trace(
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


async def _run_dify_metadata_anchor_fallback(
    ctx: _DifyExternalRetrievalContext,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    call_kwargs = dict(kwargs)
    call_kwargs.pop("db", None)
    fallback_started = time.perf_counter()
    budget_deadline: float | None = None
    if not ctx.fast_latency_profile and ctx.metadata_anchor_total_budget_ms:
        remaining_ms = ctx.metadata_anchor_total_budget_ms - int(ctx.metadata_anchor_budget_spent_ms)
        if remaining_ms <= 0:
            return []
        configured_call_budget = call_kwargs.get("max_elapsed_ms")
        if configured_call_budget is not None and int(configured_call_budget or 0) > 0:
            remaining_ms = min(remaining_ms, int(configured_call_budget))
        call_kwargs["max_elapsed_ms"] = remaining_ms
        budget_deadline = fallback_started + remaining_ms / 1000
    rollback = getattr(ctx.db, "rollback", None)
    if callable(rollback):
        rollback()
    try:
        return await metadata_anchor.run_with_deadline(call_kwargs, budget_deadline=budget_deadline)
    finally:
        ctx.metadata_anchor_budget_spent_ms += max(0.0, (time.perf_counter() - fallback_started) * 1000)
        ctx.stage_timings_ms["metadata_anchor_budget_spent_ms"] = round(ctx.metadata_anchor_budget_spent_ms, 2)


def _dify_metadata_anchor_preflight_enabled(ctx: _DifyExternalRetrievalContext) -> bool:
    return bool(
        settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED
        and ctx.metadata_anchor_db_fallback_enabled
        and (
            not ctx.fast_latency_profile
            or metadata_anchor._query_has_specific_fast_metadata_anchor_candidate(
                ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs
            )
        )
        and not ctx.metadata_filter
        and query_policy._query_allows_metadata_anchor_preflight(
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
        db=ctx.db,
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
    ctx.stage_timings_ms["metadata_preflight_accepted"] = bool(has_preflight_anchor)
    if has_preflight_anchor:
        ctx.metadata_anchor_fallback_count = len(metadata_anchor_records)
        ctx.records.extend(metadata_anchor_records)
        ctx.retrieval_path = "metadata_anchor:preflight"
        _set_main_trace_query(ctx, ctx.retrieval_path)


def _filtered_metadata_preflight_records(
    ctx: _DifyExternalRetrievalContext,
    metadata_anchor_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if ctx.query_prefers_service_anchor and scoring._query_has_quoted_anchor_candidate(ctx.body.query):
        metadata_anchor_records = [
            record
            for record in metadata_anchor_records
            if record_ranking._record_matches_quoted_query_anchor_for_policy(
                record,
                query=ctx.body.query,
                policy_plugin_refs=ctx.policy_plugin_refs,
            )
        ]
    if query_policy._query_has_mixed_intent_for_policy(
        ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs
    ) and scoring._query_has_quoted_anchor_candidate(ctx.body.query):
        metadata_anchor_records = record_processing._compact_mixed_intent_exact_anchor_records(
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
        return record_ranking._records_have_confident_metadata_anchor(
            metadata_anchor_records,
            query=ctx.body.query,
            policy_plugin_refs=ctx.policy_plugin_refs,
        )
    return record_ranking._records_have_strong_question_anchor(
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
        and query_policy._query_has_mixed_intent_for_policy(ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs)
        and not scoring._query_has_quoted_anchor_candidate(ctx.body.query)
    )


async def _apply_mixed_intent_preflight(ctx: _DifyExternalRetrievalContext) -> None:
    if not _dify_mixed_intent_preflight_enabled(ctx):
        return
    mixed_intent_queries = query_policy._mixed_intent_retrieval_queries(
        ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs
    )
    mixed_preflight_records: list[dict[str, Any]] = []
    mixed_preflight_query_count = 0
    mixed_preflight_trace_queries: list[dict[str, Any]] = []
    mixed_intent_subquery_top_k = request_preferences._resolve_mixed_intent_subquery_top_k(
        response_top_k=ctx.top_k,
        candidate_top_k=ctx.candidate_top_k,
    )
    for subquery in mixed_intent_queries:
        if not _subquery_allows_metadata_anchor_preflight(subquery, policy_plugin_refs=ctx.policy_plugin_refs):
            return
        subquery_anchor_records = await _run_dify_metadata_anchor_fallback(
            ctx,
            db=ctx.db,
            tenant_id=ctx.actor.tenant_id,
            dataset_ids=ctx.metadata_anchor_dataset_ids,
            query=subquery,
            top_k=mixed_intent_subquery_top_k,
            policy_plugin_refs=ctx.policy_plugin_refs,
            existing_records=[],
            metadata_filter=ctx.metadata_filter,
            prefer_question_anchor_first=True,
        )
        subquery_anchor_records = record_ranking._filter_records_by_mixed_intent_subject_anchor(
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
        mixed_preflight_records.extend(
            record_values._tag_mixed_intent_records(subquery_anchor_records, subquery=subquery)
        )
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
    return query_policy._query_allows_metadata_anchor_preflight(
        subquery,
        query_prefers_question_anchor=query_policy._query_prefers_question_anchor(
            subquery, policy_plugin_refs=policy_plugin_refs
        ),
        query_prefers_service_anchor=query_policy._query_prefers_service_anchor(
            subquery, policy_plugin_refs=policy_plugin_refs
        ),
        policy_plugin_refs=policy_plugin_refs,
    )


async def _retrieve_primary_records(ctx: _DifyExternalRetrievalContext) -> None:
    primary_retrieve_started = time.perf_counter()
    primary_citations = await evidence_adapter.retrieve_dataset_citations(
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
        await citation_records._records_from_citations_with_managed_hydration(
            db=ctx.db,
            tenant_id=ctx.actor.tenant_id,
            citations=primary_citations,
            fallback_dataset_id=ctx.primary_dataset_ids[0] if ctx.primary_dataset_ids else None,
            query=ctx.body.query,
            policy_plugin_refs=ctx.policy_plugin_refs,
        )
    )
    ctx.stage_timings_ms["primary_records_from_citations_ms"] = round((time.perf_counter() - records_started) * 1000, 2)


def _dify_mixed_intent_supplement_enabled(ctx: _DifyExternalRetrievalContext) -> bool:
    return bool(not ctx.fast_latency_profile and settings.DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED)


async def _apply_mixed_intent_supplement(ctx: _DifyExternalRetrievalContext) -> None:
    mixed_intent_supplement_skipped = record_ranking._records_have_exact_anchor_full_answer(
        ctx.records,
        query=ctx.body.query,
        policy_plugin_refs=ctx.policy_plugin_refs,
    )
    if mixed_intent_supplement_skipped:
        ctx.retrieval_path = f"{ctx.retrieval_path}:mixed_intent_skip_exact_anchor"
    if not (_dify_mixed_intent_supplement_enabled(ctx) and not mixed_intent_supplement_skipped):
        return
    mixed_intent_queries = query_policy._mixed_intent_retrieval_queries(
        ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs
    )
    mixed_intent_subquery_top_k = request_preferences._resolve_mixed_intent_subquery_top_k(
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
            db=ctx.db,
            tenant_id=ctx.actor.tenant_id,
            dataset_ids=ctx.primary_dataset_ids,
            query=subquery,
            top_k=mixed_intent_subquery_top_k,
            policy_plugin_refs=ctx.policy_plugin_refs,
            existing_records=[],
            metadata_filter=ctx.metadata_filter,
            prefer_question_anchor_first=not scoring._query_has_quoted_anchor_candidate(ctx.body.query),
        )
        subquery_anchor_records = record_ranking._filter_records_by_mixed_intent_subject_anchor(
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
        ctx.records.extend(record_values._tag_mixed_intent_records(subquery_anchor_records, subquery=subquery))
        return
    subquery_citations = await evidence_adapter.retrieve_dataset_citations(
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
    subquery_records = await citation_records._records_from_citations_with_managed_hydration(
        db=ctx.db,
        tenant_id=ctx.actor.tenant_id,
        citations=subquery_citations,
        fallback_dataset_id=ctx.primary_dataset_ids[0] if ctx.primary_dataset_ids else None,
        query=subquery,
        hydration_query=ctx.body.query,
        policy_plugin_refs=ctx.policy_plugin_refs,
    )
    ctx.records.extend(record_values._tag_mixed_intent_records(subquery_records, subquery=subquery))


async def _apply_kg_on_demand(ctx: _DifyExternalRetrievalContext) -> None:
    if not (ctx.requested_kg_flags.enabled and ctx.kg_on_demand_enabled):
        return
    if record_ranking._records_can_skip_kg_on_demand(
        ctx.records, query=ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs
    ):
        ctx.kg_on_demand_skipped = True
        ctx.retrieval_path = f"{ctx.retrieval_path}:kg_on_demand_skip"
        return
    kg_records = await kg_on_demand._dify_kg_on_demand_records(
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
    if record_ranking._records_meet_primary_scope(
        ctx.records, query=ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs
    ):
        return
    ctx.retrieval_path = "rag:primary_scope+expansion_scope"
    expansion_citations = await evidence_adapter.retrieve_dataset_citations(
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
        await citation_records._records_from_citations_with_managed_hydration(
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
    if record_ranking._records_can_skip_metadata_anchor_fallback(
        ctx.records, query=ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs
    ):
        return
    metadata_anchor_records = await _run_dify_metadata_anchor_fallback(
        ctx,
        db=ctx.db,
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
    ctx.query_prefers_question_anchor = query_policy._query_prefers_question_anchor(
        ctx.body.query, policy_plugin_refs=ctx.policy_plugin_refs
    )
    ctx.query_prefers_service_anchor = query_policy._query_prefers_service_anchor(
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
        return
    await _retrieve_primary_records(ctx)
    await _apply_mixed_intent_supplement(ctx)
    await _apply_kg_on_demand(ctx)
    await _apply_expansion_scope(ctx)
    await _apply_metadata_anchor_fallback_to_records(ctx)


async def _prepare_dify_external_records(ctx: _DifyExternalRetrievalContext) -> record_processing.FinalizedRecords:
    ctx.citation_count = ctx.primary_citation_count + ctx.expansion_citation_count + ctx.mixed_intent_citation_count
    postprocess_started = time.perf_counter()
    if ctx.external_reranker_enabled:
        with contextlib.suppress(Exception):
            ctx.db.rollback()
    finalized = await record_processing.finalize_records(
        records=ctx.records,
        query=ctx.body.query,
        top_k=ctx.top_k,
        response_top_k=ctx.response_top_k,
        policy_plugin_refs=ctx.policy_plugin_refs,
        fast=ctx.fast_latency_profile,
        rerank=ctx.external_reranker_enabled,
    )
    ctx.records = finalized.ranked_records
    ctx.stage_timings_ms["postprocess_ms"] = round((time.perf_counter() - postprocess_started) * 1000, 2)
    ctx.finalized_records = finalized
    return finalized


def _finish_dify_external_retrieval(
    ctx: _DifyExternalRetrievalContext, finalized: record_processing.FinalizedRecords
) -> DifyExternalKnowledgeResponse:
    response_records = finalized.records
    policy_diagnostics = finalized.policy_diagnostics
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
    tracing._log_dify_external_rag_trace(
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


def _response_from_dify_cache(
    ctx: _DifyExternalRetrievalContext, cached: response_cache.DifyCacheResult
) -> DifyExternalKnowledgeResponse:
    elapsed_ms = round((time.perf_counter() - ctx.started) * 1000, 2)
    response_records = [DifyExternalKnowledgeRecord(**record) for record in cached.records]
    if cached.source == "cache_hit":
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
    elif cached.source == "singleflight_hit":
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
    elif cached.source == "distributed_cache_hit":
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
    if cached.source in {"cache_hit", "singleflight_hit"}:
        _log_dify_short_circuit_trace(
            ctx, response_records=response_records, retrieval_path=cached.source, elapsed_ms=elapsed_ms
        )
    return DifyExternalKnowledgeResponse(records=response_records)


def _log_dify_external_retrieval_failure(ctx: _DifyExternalRetrievalContext) -> None:
    elapsed_ms = round((time.perf_counter() - ctx.started) * 1000, 2)
    policy_diagnostics = record_ranking._records_retrieval_policy_diagnostics(
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


async def retrieve_knowledge(
    *,
    request_headers: Mapping[str, str],
    request_id: str | None,
    client_ip: str | None,
    body: DifyExternalKnowledgeRequest,
    actor: _DifyActor,
    db: Session,
) -> DifyExternalKnowledgeResponse:
    ctx = _build_dify_external_retrieval_context(
        request_headers=request_headers, request_id=request_id, client_ip=client_ip, body=body, actor=actor, db=db
    )

    async def compute_response_records() -> list[dict[str, Any]]:
        await _execute_dify_external_retrieval(ctx)
        finalized = await _prepare_dify_external_records(ctx)
        return [record.model_dump(mode="json") for record in finalized.records]

    try:
        await _prepare_dify_response_cache_key(ctx)
        cached = await response_cache.get_or_compute_response(
            key=ctx.response_cache_key,
            compute=compute_response_records,
            policy=ctx.cache_policy,
        )
        ctx.stage_timings_ms.update(cached.timings_ms)
        if cached.source != "computed":
            return _response_from_dify_cache(ctx, cached)
        return _finish_dify_external_retrieval(ctx, ctx.finalized_records)
    except (asyncio.CancelledError, HTTPException):
        raise
    except Exception:
        _log_dify_external_retrieval_failure(ctx)
        raise
