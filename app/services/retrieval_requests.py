"""Evidence retrieval and shared preview business operations."""

import time
from typing import Any, TypedDict
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.schemas.conversations import ChatRAGConfig, EvidenceRetrieveRequest, EvidenceRetrieveResponse
from app.core.config import settings
from app.rag.core.logging import get_logger
from app.services import dataset_service
from app.services.dataset_defaults import load_dataset_metadata, resolve_single_dataset_id_for_documents
from app.services.rag_defaults import merge_rag_config_with_dataset_defaults
from app.services.rag_runtime_limiter import (
    run_blocking_call_with_managed_session,
    run_blocking_retrieval_call_with_managed_session,
)
from app.services.retrieval_scope import _resolve_retrieval_scope

logger = get_logger(__name__)


class _IterativeRetrievalResult(TypedDict):
    citations: list[dict[str, Any]]
    metrics: dict[str, Any]
    query_for_retrieval: str
    query_debug: dict[str, Any] | None
    abstain_triggered: bool
    abstain_reason: Any
    has_evidence: bool
    selected_pass: str
    fallback: dict[str, Any] | None
    iterative_summary: dict[str, Any] | None


def _merge_dataset_ids_metadata_filter(
    metadata_filter: dict[str, Any] | None,
    *,
    dataset_ids: list[UUID],
) -> dict[str, Any] | None:
    if not dataset_ids:
        return metadata_filter

    dataset_filter: dict[str, Any] = {
        "dataset_id": {"$in": [str(dataset_id) for dataset_id in dataset_ids]},
    }
    if not metadata_filter:
        return dataset_filter
    existing = dict(metadata_filter)
    if "dataset_id" not in existing:
        existing["dataset_id"] = dataset_filter["dataset_id"]
        return existing
    return {"$and": [existing, dataset_filter]}


def _resolve_multimodal_query_meta(
    *, text_query: str, enable_auto_detect: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    image_meta = {"enabled": False, "used": False, "reason": "image_vector_retrieval_retired"}
    if not enable_auto_detect:
        return {"enabled": True, "modality": "text", "reasons": []}, image_meta
    from app.rag.policy.modality_router import classify_query_modality

    modality, reasons = classify_query_modality(text_query)
    return {"enabled": True, "modality": modality, "reasons": reasons}, image_meta


def _resolve_dataset_defaults_rag_config(
    *,
    db: Session,
    tenant_id: UUID,
    scope_dataset_id: UUID | None,
    scope_document_ids: list[UUID] | None,
    rag_config: ChatRAGConfig,
    request_fields_set: set[str],
    default_profile: str | None = None,
) -> tuple[ChatRAGConfig, list[str], dict[str, Any] | None, set[str]]:
    rag_config_provided = "rag_config" in request_fields_set
    effective_rag_config = rag_config
    rag_fields_set = set(rag_config.model_fields_set)
    if default_profile and not rag_config_provided:
        effective_rag_config = ChatRAGConfig(retrieval_profile=default_profile)
        rag_fields_set = set()
    elif not rag_config_provided:
        rag_fields_set = set()

    dataset_rag_defaults_applied_fields: list[str] = []
    dataset_defaults_meta: dict[str, Any] | None = None
    ds_id = scope_dataset_id
    if ds_id is None and scope_document_ids:
        ds_id = resolve_single_dataset_id_for_documents(db, tenant_id=tenant_id, document_ids=scope_document_ids)
    if ds_id is not None:
        ds_meta = load_dataset_metadata(db, tenant_id=tenant_id, dataset_id=ds_id)
        dataset_defaults_meta = ds_meta
        raw_defaults = ds_meta.get("rag_defaults")
        effective_rag_config, dataset_rag_defaults_applied_fields = merge_rag_config_with_dataset_defaults(
            rag_config=effective_rag_config,
            request_fields_set=rag_fields_set,
            raw_dataset_defaults=raw_defaults,
        )
    return effective_rag_config, dataset_rag_defaults_applied_fields, dataset_defaults_meta, rag_fields_set


def _resolve_structure_dataset_id(
    *,
    db: Session,
    tenant_id: UUID,
    scope_dataset_id: UUID | None,
    scope_document_ids: list[UUID] | None,
) -> UUID | None:
    if scope_dataset_id is not None or not scope_document_ids:
        return scope_dataset_id
    try:
        return resolve_single_dataset_id_for_documents(
            db,
            tenant_id=tenant_id,
            document_ids=scope_document_ids,
        )
    except Exception:
        return None


def _top_relevance_score(metrics: dict[str, Any]) -> float:
    raw = metrics.get("top_relevance_score")
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _build_iterative_fallback_state(
    *,
    state: dict[str, Any],
    fallback_profile: str,
    fallback_mode: str,
) -> dict[str, Any]:
    base_k = state["top_k"]
    if fallback_profile == "recall20":
        fallback_k = max(base_k, 20)
    elif fallback_profile == "recall50":
        fallback_k = max(base_k, 50)
    else:
        fallback_k = max(base_k, 80)

    fallback_state = dict(state)
    fallback_state["retrieval_profile"] = fallback_profile
    fallback_state["retrieval_mode"] = fallback_mode
    fallback_state["top_k"] = fallback_k
    fallback_state["score_threshold"] = 0.0
    return fallback_state


async def _maybe_apply_iterative_retrieval_fallback(
    *,
    db: Session,
    state: dict[str, Any],
    citations: list[dict[str, Any]],
    metrics: dict[str, Any],
    query_for_retrieval: str,
    query_debug: dict[str, Any] | None,
    abstain_triggered: bool,
    has_evidence: bool,
) -> _IterativeRetrievalResult:
    iterative_enabled = settings.EVIDENCE_ITERATIVE_RETRIEVE_ENABLED
    max_passes = max(1, settings.EVIDENCE_ITERATIVE_RETRIEVE_MAX_PASSES)

    result: _IterativeRetrievalResult = {
        "citations": citations,
        "metrics": metrics,
        "query_for_retrieval": query_for_retrieval,
        "query_debug": query_debug,
        "abstain_triggered": abstain_triggered,
        "abstain_reason": metrics.get("abstain_reason"),
        "has_evidence": has_evidence,
        "selected_pass": "primary",
        "fallback": None,
        "iterative_summary": None,
    }
    if not iterative_enabled or max_passes < 2 or has_evidence:
        return result

    from app.rag.core.text import normalize_retrieval_mode
    from app.rag.retrieval.orchestrator import run_retrieval

    fallback_profile = str(settings.EVIDENCE_ITERATIVE_RETRIEVE_FALLBACK_PROFILE).strip().lower()
    if fallback_profile not in {"recall20", "recall50", "coverage80"}:
        fallback_profile = "coverage80"

    fallback_mode = str(settings.EVIDENCE_ITERATIVE_RETRIEVE_FALLBACK_MODE).strip().lower()
    fallback_mode = normalize_retrieval_mode(fallback_mode)
    if fallback_mode not in {"hybrid", "vector", "keyword", "mmr"}:
        fallback_mode = "keyword"

    fallback_state = _build_iterative_fallback_state(
        state=state,
        fallback_profile=fallback_profile,
        fallback_mode=fallback_mode,
    )
    fallback_offload_metrics: dict[str, Any] = {}
    fallback = (
        await run_blocking_retrieval_call_with_managed_session(
            lambda worker_db: run_retrieval({**fallback_state, "db": worker_db}),
            request_db=db,
            runtime_metrics=fallback_offload_metrics,
        )
        or {}
    )
    f_citations = fallback.get("citations") or []
    f_metrics = dict(fallback.get("metrics") or {})
    f_metrics.update(fallback_offload_metrics)
    f_abstain = bool(fallback.get("abstain_triggered") or f_metrics.get("abstain_triggered") or False)
    f_has_evidence = bool(f_citations) and not f_abstain

    p_top = _top_relevance_score(metrics)
    f_top = _top_relevance_score(f_metrics)
    p_n = len(citations) if isinstance(citations, list) else 0
    f_n = len(f_citations) if isinstance(f_citations, list) else 0

    use_fallback = False
    if f_has_evidence and not has_evidence:
        use_fallback = True
    elif f_has_evidence and has_evidence:
        use_fallback = f_top > p_top
    elif (not f_has_evidence) and (not has_evidence):
        use_fallback = (f_top > p_top) or (f_top == p_top and f_n > p_n)

    iterative_summary = {
        "enabled": True,
        "max_passes": max_passes,
        "selected_pass": "fallback" if use_fallback else "primary",
        "passes": [
            {
                "pass": "primary",
                "retrieval_mode": metrics.get("retrieval_mode"),
                "retrieval_profile": state.get("retrieval_profile"),
                "empty_retrieval": metrics.get("empty_retrieval")
                if isinstance(metrics.get("empty_retrieval"), dict)
                else None,
                "citations": p_n,
                "top_relevance_score": round(p_top, 3),
                "abstain_triggered": bool(abstain_triggered),
                "has_evidence": bool(has_evidence),
                "retrieval_elapsed_sec": float(metrics.get("retrieval_elapsed_sec") or 0.0),
            },
            {
                "pass": "fallback",
                "retrieval_mode": f_metrics.get("retrieval_mode"),
                "retrieval_profile": fallback_profile,
                "empty_retrieval": f_metrics.get("empty_retrieval")
                if isinstance(f_metrics.get("empty_retrieval"), dict)
                else None,
                "citations": f_n,
                "top_relevance_score": round(f_top, 3),
                "abstain_triggered": f_abstain,
                "has_evidence": f_has_evidence,
                "retrieval_elapsed_sec": float(f_metrics.get("retrieval_elapsed_sec") or 0.0),
            },
        ],
    }
    result["fallback"] = fallback
    result["iterative_summary"] = iterative_summary
    if not use_fallback:
        return result

    result["citations"] = f_citations
    result["metrics"] = f_metrics
    result["query_for_retrieval"] = (fallback["query_for_retrieval"]).strip()
    qd = fallback.get("query_debug")
    result["query_debug"] = qd if isinstance(qd, dict) else query_debug
    result["abstain_triggered"] = f_abstain
    result["abstain_reason"] = fallback.get("abstain_reason")
    result["has_evidence"] = f_has_evidence
    result["selected_pass"] = "fallback"
    return result


def _apply_min_top_relevance_gate(
    *,
    citations: list[dict[str, Any]],
    metrics: dict[str, Any],
    has_evidence: bool,
) -> bool:
    min_top_rel = float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE)
    if not has_evidence or min_top_rel <= 0.0:
        return has_evidence

    top_rel_raw = metrics.get("top_relevance_score")
    try:
        top_rel = float(top_rel_raw) if top_rel_raw is not None else None
    except (TypeError, ValueError, OverflowError):
        top_rel = None
    if top_rel is None and isinstance(citations, list) and citations:
        try:
            top_rel = max(
                float(
                    (
                        (c.get("relevance_score") if c.get("relevance_score") is not None else c.get("retrieval_score"))
                        or 0.0
                    )
                )
                for c in citations
                if isinstance(c, dict)
            )
        except (TypeError, ValueError, OverflowError):
            top_rel = None
    if top_rel is not None and top_rel < min_top_rel:
        return False
    return has_evidence


def _build_retrieval_trace_payload(
    *,
    primary: dict[str, Any],
    fallback: dict[str, Any] | None,
    selected_pass: str,
) -> dict[str, Any] | None:
    try:
        passes: list[dict[str, Any]] = []
        primary_trace = primary.get("retrieval_trace")
        if isinstance(primary_trace, dict):
            passes.append({"pass": "primary", "trace": primary_trace})
        fallback_trace = fallback.get("retrieval_trace") if isinstance(fallback, dict) else None
        if isinstance(fallback_trace, dict):
            passes.append({"pass": "fallback", "trace": fallback_trace})
        if passes:
            return {
                "schema": "mimirq.retrieval_trace.v1",
                "selected_pass": str(selected_pass),
                "passes": passes,
            }
    except Exception:
        return None
    return None


def _build_evidence_capsule_payload(
    *,
    query_for_retrieval: str,
    citations: list[dict[str, Any]],
    metrics: dict[str, Any],
    retrieval_trace_payload: dict[str, Any] | None,
    query_debug: dict[str, Any] | None,
    tenant_id: UUID,
    scope_dataset_id: UUID | None,
    scope_dataset_ids: list[UUID],
    scope_document_ids: list[UUID] | None,
    selected_pass: str,
) -> dict[str, Any] | None:
    try:
        if not bool(settings.RAG_EVIDENCE_CAPSULE_ENABLED):
            return None
        from app.rag.core.evidence_capsule_builder import build_evidence_capsule

        return build_evidence_capsule(
            query_for_retrieval=query_for_retrieval,
            citations=[c for c in citations if isinstance(c, dict)],
            metrics=metrics,
            retrieval_trace=retrieval_trace_payload,
            query_debug=query_debug if isinstance(query_debug, dict) else None,
            request_context={
                "tenant_id": str(tenant_id),
                "dataset_id": str(scope_dataset_id) if scope_dataset_id else None,
                "dataset_ids": [str(dataset_id) for dataset_id in scope_dataset_ids],
                "document_ids": None if scope_document_ids is None else [str(d) for d in scope_document_ids[:200]],
                "selected_pass": str(selected_pass),
            },
        )
    except Exception:
        return None


def _observe_evidence_retrieve_metrics(
    *,
    t_api_start: float,
    metrics: dict[str, Any],
    effective_rag_config: ChatRAGConfig,
    selected_pass: str,
    citations: list[dict[str, Any]],
    has_evidence: bool,
    abstain_triggered: bool,
) -> None:
    try:
        from app.rag.retrieval.metrics import observe_evidence_retrieve

        observe_evidence_retrieve(
            duration_sec=(time.monotonic() - t_api_start),
            has_evidence=bool(has_evidence),
            abstain_triggered=bool(abstain_triggered),
            retrieval_mode=metrics.get("retrieval_mode"),
            selected_pass=str(selected_pass),
            citations_count=(len(citations) if isinstance(citations, list) else 0),
            top_relevance_score=float(_top_relevance_score(metrics) or 0.0),
        )
    except Exception as exc:
        logger.debug("Failed to record retrieval preview metrics: %s", exc)


def _build_document_structure_trace(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID | None,
    citations: list[dict[str, Any]],
    max_documents: int = 5,
    max_nodes: int = 120,
) -> dict[str, Any] | None:
    if dataset_id is None or not citations:
        return None
    try:
        from app.rag.retrieval.document_structure import (
            explain_citations_with_structure,
            load_structures_for_citations,
        )

        structures = load_structures_for_citations(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            citations=citations,
            max_documents=max_documents,
            max_nodes=max_nodes,
        )
        if not structures:
            return None
        selected_sections = explain_citations_with_structure(
            citations=citations,
            structures_by_document=structures,
        )
        return {
            "schema": "mimirq.document_structure_trace.v1",
            "document_count": len(structures),
            "documents": list(structures.values()),
            "selected_sections": selected_sections,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "mimirq.document_structure_trace.v1",
            "document_count": 0,
            "documents": [],
            "selected_sections": [],
            "error": str(exc)[:160],
        }


def _attach_document_structure_trace(
    *,
    metrics: dict[str, Any],
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID | None,
    citations: list[dict[str, Any]],
    max_documents: int = 5,
    max_nodes: int = 120,
) -> dict[str, Any] | None:
    trace = _build_document_structure_trace(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        citations=citations,
        max_documents=max_documents,
        max_nodes=max_nodes,
    )
    if trace:
        metrics.setdefault("document_structure_trace", trace)
    return trace


async def retrieve_evidence(body: EvidenceRetrieveRequest, *, tenant_id: UUID, account_id: str, db: Session):
    """
    Execute retrieval only (no answer generation) and return evidence chunks.

    Defaults to a recall-first profile when the caller omits rag_config.
    """
    t_api_start = time.monotonic()
    await run_blocking_call_with_managed_session(
        lambda worker_db: dataset_service.ensure_member(worker_db, tenant_id, account_id), request_db=None
    )
    from app.services.tenant_quota_service import enforce_tenant_qps_quota_async

    tenant_qps_meta = await enforce_tenant_qps_quota_async(tenant_id=tenant_id, key="retrieval")
    from app.rag.pipelines.langgraph import build_rag_state
    from app.rag.retrieval.orchestrator import run_retrieval

    def prepare_request(db: Session):
        scope_dataset_id, scope_dataset_ids, scope_document_ids = _resolve_retrieval_scope(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            document_ids=body.document_ids,
            dataset_id=body.dataset_id,
            dataset_ids=body.dataset_ids,
            allow_multi_dataset=True,
        )
        request_fields_set = set(body.model_fields_set)
        effective_rag_config, dataset_rag_defaults_applied_fields, _dataset_defaults_meta, _rag_fields_set = (
            _resolve_dataset_defaults_rag_config(
                db=db,
                tenant_id=tenant_id,
                scope_dataset_id=scope_dataset_id,
                scope_document_ids=scope_document_ids,
                rag_config=body.rag_config,
                request_fields_set=request_fields_set,
                default_profile="recall50",
            )
        )
        metadata_filter = _merge_dataset_ids_metadata_filter(
            effective_rag_config.metadata_filter, dataset_ids=scope_dataset_ids
        )
        state = build_rag_state(
            question=body.query,
            history=[m.model_dump() for m in body.history],
            document_ids=scope_document_ids,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=scope_dataset_id,
            dataset_ids=scope_dataset_ids,
            top_k=effective_rag_config.top_k,
            score_threshold=effective_rag_config.score_threshold,
            retrieval_mode=effective_rag_config.retrieval_mode,
            retrieval_profile=effective_rag_config.retrieval_profile,
            retrieval_contract_mode=effective_rag_config.retrieval_contract_mode,
            must_recall=effective_rag_config.must_recall,
            must_recall_expected_source_keys=effective_rag_config.must_recall_expected_source_keys,
            must_recall_required_anchor_fields=effective_rag_config.must_recall_required_anchor_fields,
            intent_router=effective_rag_config.intent_router,
            intent_router_policy=effective_rag_config.intent_router_policy,
            enable_query_alias_expansion=effective_rag_config.enable_query_alias_expansion,
            query_aliases=effective_rag_config.query_aliases,
            query_alias_max_queries=effective_rag_config.query_alias_max_queries,
            enable_multi_query=effective_rag_config.enable_multi_query,
            multi_query_count=effective_rag_config.multi_query_count,
            multi_query_temperature=effective_rag_config.multi_query_temperature,
            multi_query_max_chars=effective_rag_config.multi_query_max_chars,
            enable_hyde=effective_rag_config.enable_hyde,
            enable_query_decomposition=effective_rag_config.enable_query_decomposition,
            enable_hierarchy_recall=effective_rag_config.enable_hierarchy_recall,
            hierarchy_family_collapse=effective_rag_config.hierarchy_family_collapse,
            hierarchy_family_aggregation=effective_rag_config.hierarchy_family_aggregation,
            hierarchy_tree_dedup=effective_rag_config.hierarchy_tree_dedup,
            hierarchy_parent_depth=effective_rag_config.hierarchy_parent_depth,
            hierarchy_sibling_window=effective_rag_config.hierarchy_sibling_window,
            hierarchy_overfetch_factor=effective_rag_config.hierarchy_overfetch_factor,
            enable_kg_query_expansion=effective_rag_config.enable_kg_query_expansion,
            enable_kg_chunk_injection=effective_rag_config.enable_kg_chunk_injection,
            kg_chunk_injection_max_chunks=effective_rag_config.kg_chunk_injection_max_chunks,
            enable_kg_chunk_boost=effective_rag_config.enable_kg_chunk_boost,
            kg_chunk_boost_weight=effective_rag_config.kg_chunk_boost_weight,
            kg_chunk_boost_max_promoted=effective_rag_config.kg_chunk_boost_max_promoted,
            lexical_db_hybrid_fallback_only=effective_rag_config.lexical_db_hybrid_fallback_only,
            lexical_db_hybrid_metadata_exact_fallback_enabled=effective_rag_config.lexical_db_hybrid_metadata_exact_fallback_enabled,
            metadata_exact_db_fallback_enabled=effective_rag_config.metadata_exact_db_fallback_enabled,
            alpha=effective_rag_config.alpha,
            fusion_strategy=effective_rag_config.fusion_strategy,
            fusion_budgets=effective_rag_config.fusion_budgets,
            fusion_min_scores=effective_rag_config.fusion_min_scores,
            fusion_weights=effective_rag_config.fusion_weights,
            retrieval_overfetch_multiplier=effective_rag_config.retrieval_overfetch_multiplier,
            retrieval_overfetch_max_k=effective_rag_config.retrieval_overfetch_max_k,
            enable_weight_rerank=effective_rag_config.enable_weight_rerank,
            vector_weight=effective_rag_config.vector_weight,
            keyword_weight=effective_rag_config.keyword_weight,
            mmr_lambda=effective_rag_config.mmr_lambda,
            enable_reranker=effective_rag_config.enable_reranker,
            reranker_provider=effective_rag_config.reranker_provider,
            reranker_top_n=effective_rag_config.reranker_top_n,
            metadata_filter=metadata_filter,
            visible_evidence_only=effective_rag_config.visible_evidence_only,
            ab_user_key=account_id,
            db=db,
        )
        if body.seed is not None:
            state["seed"] = body.seed
        multimodal_meta, image_meta = _resolve_multimodal_query_meta(text_query=body.query, enable_auto_detect=True)
        state["multimodal_router"] = multimodal_meta
        state["image_meta"] = image_meta
        return (
            dataset_rag_defaults_applied_fields,
            effective_rag_config,
            image_meta,
            multimodal_meta,
            scope_dataset_id,
            scope_dataset_ids,
            scope_document_ids,
            state,
        )

    (
        dataset_rag_defaults_applied_fields,
        effective_rag_config,
        image_meta,
        multimodal_meta,
        scope_dataset_id,
        scope_dataset_ids,
        scope_document_ids,
        state,
    ) = await run_blocking_call_with_managed_session(prepare_request, request_db=None)
    primary_offload_metrics: dict[str, Any] = {}
    primary = (
        await run_blocking_retrieval_call_with_managed_session(
            lambda worker_db: run_retrieval({**state, "db": worker_db}),
            request_db=db,
            runtime_metrics=primary_offload_metrics,
        )
        or {}
    )
    citations = primary.get("citations") or []
    metrics = dict(primary.get("metrics") or {})
    metrics.update(primary_offload_metrics)
    query_for_retrieval = primary["query_for_retrieval"].strip()
    query_debug = primary.get("query_debug")
    if not isinstance(query_debug, dict):
        query_debug = None
    metrics.setdefault("vector_backend", settings.VECTOR_BACKEND)
    metrics.setdefault("requested_retrieval_mode", effective_rag_config.retrieval_mode)
    metrics.setdefault("multimodal_router", multimodal_meta)
    metrics.setdefault("image", image_meta)
    if dataset_rag_defaults_applied_fields:
        metrics.setdefault("dataset_rag_defaults_applied", True)
        metrics.setdefault("dataset_rag_defaults_fields", dataset_rag_defaults_applied_fields)
    if scope_dataset_ids:
        metrics.setdefault("scope_dataset_ids", [str(dataset_id) for dataset_id in scope_dataset_ids])
    abstain_triggered = bool(primary.get("abstain_triggered") or metrics.get("abstain_triggered") or False)
    has_evidence = bool(citations) and (not abstain_triggered)
    iterative_result = await _maybe_apply_iterative_retrieval_fallback(
        db=db,
        state=state,
        citations=citations,
        metrics=metrics,
        query_for_retrieval=query_for_retrieval,
        query_debug=query_debug,
        abstain_triggered=abstain_triggered,
        has_evidence=has_evidence,
    )
    citations = iterative_result["citations"]
    metrics = iterative_result["metrics"]
    query_for_retrieval = iterative_result["query_for_retrieval"]
    query_debug = iterative_result["query_debug"]
    abstain_triggered = iterative_result["abstain_triggered"]
    abstain_reason = iterative_result["abstain_reason"]
    has_evidence = _apply_min_top_relevance_gate(
        citations=[c for c in citations if isinstance(c, dict)],
        metrics=metrics,
        has_evidence=iterative_result["has_evidence"],
    )
    selected_pass = iterative_result["selected_pass"]
    fallback = iterative_result["fallback"]
    iterative_summary = iterative_result["iterative_summary"]
    if iterative_summary and isinstance(iterative_summary, dict):
        metrics.setdefault("iterative_retrieve", iterative_summary)
        if isinstance(query_debug, dict):
            query_debug.setdefault("iterative_retrieve", iterative_summary)
    metrics.setdefault("tenant_qps_quota", tenant_qps_meta)

    def attach_structure(__db: Session):
        db = __db
        structure_dataset_id = _resolve_structure_dataset_id(
            db=db, tenant_id=tenant_id, scope_dataset_id=scope_dataset_id, scope_document_ids=scope_document_ids
        )
        _attach_document_structure_trace(
            metrics=metrics,
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=structure_dataset_id,
            citations=[c for c in citations if isinstance(c, dict)],
        )

    await run_blocking_call_with_managed_session(attach_structure, request_db=None)
    _observe_evidence_retrieve_metrics(
        t_api_start=t_api_start,
        metrics=metrics,
        effective_rag_config=effective_rag_config,
        selected_pass=selected_pass,
        citations=[c for c in citations if isinstance(c, dict)],
        has_evidence=bool(has_evidence),
        abstain_triggered=bool(abstain_triggered),
    )
    retrieval_trace_payload = _build_retrieval_trace_payload(
        primary=primary, fallback=fallback if isinstance(fallback, dict) else None, selected_pass=selected_pass
    )
    evidence_capsule = _build_evidence_capsule_payload(
        query_for_retrieval=query_for_retrieval,
        citations=[c for c in citations if isinstance(c, dict)],
        metrics=metrics,
        retrieval_trace_payload=retrieval_trace_payload,
        query_debug=query_debug if isinstance(query_debug, dict) else None,
        tenant_id=tenant_id,
        scope_dataset_id=scope_dataset_id,
        scope_dataset_ids=scope_dataset_ids,
        scope_document_ids=scope_document_ids,
        selected_pass=selected_pass,
    )
    return EvidenceRetrieveResponse(
        query_for_retrieval=query_for_retrieval,
        citations=citations,
        metrics=metrics,
        has_evidence=has_evidence,
        abstain_triggered=abstain_triggered,
        abstain_reason=abstain_reason,
        retrieval_trace=retrieval_trace_payload,
        evidence_capsule=evidence_capsule,
        query_debug=query_debug,
    )
