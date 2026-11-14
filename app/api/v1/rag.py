"""
RAG debug/preview API.

For debugging and validating:
- Retrieval parameters (top_k/threshold/mode/weight)
- Access control (tenant + account + document_ids)
"""

import time
from collections.abc import Callable
from typing import Annotated, Any, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.conversations import (
    ChatRAGConfig,
    DocumentStructureRequest,
    EvidenceRetrieveRequest,
    EvidenceRetrieveResponse,
    PromptPreviewRequest,
    PromptPreviewResponse,
    RetrievePreviewRequest,
    RetrievePreviewResponse,
    TreeSearchPreviewRequest,
    TreeSearchPreviewResponse,
)
from app.core.async_bridge import run_blocking_in_thread
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.services import dataset_service
from app.services.rag_config_template_apply import apply_rag_config_patch
from app.services.rag_config_template_defaults import merge_rag_config_template_defaults_with_dataset
from app.services.rag_config_template_resolver import (
    build_rag_config_patch_hash,
    record_rag_config_template_usage,
    resolve_rag_config_template,
)
from app.services.rag_runtime_limiter import run_blocking_retrieval_call_with_managed_session
from app.services.retrieval_requests import (
    _attach_document_structure_trace,
    _build_document_structure_trace,
    _merge_dataset_ids_metadata_filter,
    _resolve_dataset_defaults_rag_config,
    _resolve_multimodal_query_meta,
    _resolve_structure_dataset_id,
)
from app.services.retrieval_requests import retrieve_evidence as retrieve_evidence_impl
from app.services.retrieval_scope import _resolve_retrieval_scope

_T = TypeVar("_T")

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
    503: {"description": "Service Unavailable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


async def _run_preview_db_call(operation: Callable[[Session], _T]) -> _T:
    """Keep metadata work and session cleanup together through request cancellation."""

    def run() -> _T:
        with SessionLocal() as worker_db:
            return operation(worker_db)

    return await run_blocking_in_thread(run)


def _preview_retrieval_options(config: ChatRAGConfig) -> dict[str, Any]:
    """Map the retrieval options shared by retrieval and prompt previews."""
    return {
        "top_k": config.top_k,
        "score_threshold": config.score_threshold,
        "retrieval_mode": config.retrieval_mode,
        "retrieval_profile": config.retrieval_profile,
        "retrieval_contract_mode": config.retrieval_contract_mode,
        "must_recall": config.must_recall,
        "must_recall_expected_source_keys": config.must_recall_expected_source_keys,
        "must_recall_required_anchor_fields": config.must_recall_required_anchor_fields,
        "intent_router": config.intent_router,
        "intent_router_policy": config.intent_router_policy,
        "enable_query_alias_expansion": config.enable_query_alias_expansion,
        "query_aliases": config.query_aliases,
        "query_alias_max_queries": config.query_alias_max_queries,
        "enable_multi_query": config.enable_multi_query,
        "multi_query_count": config.multi_query_count,
        "multi_query_temperature": config.multi_query_temperature,
        "multi_query_max_chars": config.multi_query_max_chars,
        "enable_hyde": config.enable_hyde,
        "enable_query_decomposition": config.enable_query_decomposition,
        "enable_hierarchy_recall": config.enable_hierarchy_recall,
        "hierarchy_family_collapse": config.hierarchy_family_collapse,
        "hierarchy_family_aggregation": config.hierarchy_family_aggregation,
        "hierarchy_tree_dedup": config.hierarchy_tree_dedup,
        "hierarchy_parent_depth": config.hierarchy_parent_depth,
        "hierarchy_sibling_window": config.hierarchy_sibling_window,
        "hierarchy_overfetch_factor": config.hierarchy_overfetch_factor,
        "enable_kg_query_expansion": config.enable_kg_query_expansion,
        "enable_kg_chunk_injection": config.enable_kg_chunk_injection,
        "kg_chunk_injection_max_chunks": config.kg_chunk_injection_max_chunks,
        "enable_kg_chunk_boost": config.enable_kg_chunk_boost,
        "kg_chunk_boost_weight": config.kg_chunk_boost_weight,
        "kg_chunk_boost_max_promoted": config.kg_chunk_boost_max_promoted,
        "alpha": config.alpha,
        "fusion_strategy": config.fusion_strategy,
        "fusion_budgets": config.fusion_budgets,
        "fusion_min_scores": config.fusion_min_scores,
        "fusion_weights": config.fusion_weights,
        "retrieval_overfetch_multiplier": config.retrieval_overfetch_multiplier,
        "retrieval_overfetch_max_k": config.retrieval_overfetch_max_k,
        "enable_weight_rerank": config.enable_weight_rerank,
        "vector_weight": config.vector_weight,
        "keyword_weight": config.keyword_weight,
        "mmr_lambda": config.mmr_lambda,
        "enable_reranker": config.enable_reranker,
        "reranker_provider": config.reranker_provider,
        "reranker_top_n": config.reranker_top_n,
        "visible_evidence_only": config.visible_evidence_only,
    }


def _resolve_preview_rag_template_meta(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    body: RetrievePreviewRequest,
    request_fields_set: set[str],
    dataset_defaults_meta: dict[str, Any] | None,
    effective_rag_config: ChatRAGConfig,
    rag_fields_set: set[str],
) -> tuple[ChatRAGConfig, dict[str, Any] | None, list[str]]:
    (
        effective_rag_config_template_id,
        effective_rag_config_template_key,
        effective_rag_config_ab_experiment_key,
        dataset_rag_config_template_defaults_applied_fields,
    ) = merge_rag_config_template_defaults_with_dataset(
        rag_config_template_id=body.rag_config_template_id,
        rag_config_template_key=body.rag_config_template_key,
        rag_config_ab_experiment_key=body.rag_config_ab_experiment_key,
        request_fields_set=request_fields_set,
        dataset_meta=dataset_defaults_meta,
    )

    rag_config_template_meta: dict[str, Any] | None = None
    if (
        effective_rag_config_template_id
        or (effective_rag_config_template_key is not None and effective_rag_config_template_key.strip())
        or (effective_rag_config_ab_experiment_key is not None and effective_rag_config_ab_experiment_key.strip())
    ):
        chosen, resolver_debug = resolve_rag_config_template(
            db=db,
            tenant_id=tenant_id,
            rag_config_template_id=effective_rag_config_template_id,
            template_key=effective_rag_config_template_key,
            ab_experiment_key=effective_rag_config_ab_experiment_key,
            ab_user_key=account_id,
            return_debug_metadata=True,
        )
        if chosen is not None:
            effective_rag_config, rag_config_template_patch_applied_fields = apply_rag_config_patch(
                rag_config=effective_rag_config,
                patch=chosen.config_patch,
                request_fields_set=rag_fields_set,
            )
            rag_config_template_meta = {
                "template_id": str(chosen.id),
                "template_key": chosen.template_key,
                "version": chosen.version or 0,
                "ab_experiment_key": chosen.ab_experiment_key,
                "ab_variant": chosen.ab_variant,
                "patch_hash": build_rag_config_patch_hash(chosen.config_patch),
                "patch_applied_fields": rag_config_template_patch_applied_fields,
            }
            if resolver_debug:
                rag_config_template_meta["resolver_debug"] = resolver_debug
            record_rag_config_template_usage(db, chosen)
    return (
        effective_rag_config,
        rag_config_template_meta,
        dataset_rag_config_template_defaults_applied_fields,
    )


@router.post("/document-structure", response_model=dict[str, Any])
def document_structure_preview(
    body: DocumentStructureRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Return document structure derived from existing chunk hierarchy metadata."""
    dataset_service.ensure_member(db, tenant_id, account_id)
    ds = dataset_service.get_dataset(db, tenant_id, body.dataset_id)
    dataset_service.assert_dataset_readable(db, ds, account_id)

    from app.rag.retrieval.document_structure import load_document_structure

    structure = load_document_structure(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=body.dataset_id,
        document_id=body.document_id,
        max_nodes=body.max_nodes,
    )
    error = structure.get("error")
    if error == "No document access":
        raise HTTPException(status_code=403, detail=error)
    if error == "Document not found":
        raise HTTPException(status_code=404, detail=error)
    return structure


@router.post("/retrieve-preview", response_model=RetrievePreviewResponse)
async def retrieve_preview(
    body: RetrievePreviewRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RetrievePreviewResponse:
    """Execute retrieval only (no answer generation); for parameter tuning and retrieval quality debugging."""
    await _run_preview_db_call(lambda worker_db: dataset_service.ensure_member(worker_db, tenant_id, account_id))

    # Best-effort per-tenant aggregate QPS limiter.
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
        request_fields_set = body.model_fields_set
        effective_rag_config, dataset_rag_defaults_applied_fields, dataset_defaults_meta, rag_fields_set = (
            _resolve_dataset_defaults_rag_config(
                db=db,
                tenant_id=tenant_id,
                scope_dataset_id=scope_dataset_id,
                scope_document_ids=scope_document_ids,
                rag_config=body.rag_config,
                request_fields_set=request_fields_set,
                default_profile="recall20",
            )
        )
        (
            effective_rag_config,
            rag_config_template_meta,
            dataset_rag_config_template_defaults_applied_fields,
        ) = _resolve_preview_rag_template_meta(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            body=body,
            request_fields_set=request_fields_set,
            dataset_defaults_meta=dataset_defaults_meta,
            effective_rag_config=effective_rag_config,
            rag_fields_set=rag_fields_set,
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
            **_preview_retrieval_options(effective_rag_config),
            lexical_db_hybrid_fallback_only=effective_rag_config.lexical_db_hybrid_fallback_only,
            lexical_db_hybrid_metadata_exact_fallback_enabled=effective_rag_config.lexical_db_hybrid_metadata_exact_fallback_enabled,
            metadata_exact_db_fallback_enabled=effective_rag_config.metadata_exact_db_fallback_enabled,
            metadata_filter=metadata_filter,
            ab_user_key=account_id,
            db=db,
        )
        if rag_config_template_meta:
            state["rag_config_template"] = rag_config_template_meta
        multimodal_meta, image_meta = _resolve_multimodal_query_meta(text_query=body.query, enable_auto_detect=False)
        state["multimodal_router"] = multimodal_meta
        state["image_meta"] = image_meta
        return (
            dataset_rag_config_template_defaults_applied_fields,
            dataset_rag_defaults_applied_fields,
            effective_rag_config,
            image_meta,
            multimodal_meta,
            rag_config_template_meta,
            scope_dataset_id,
            scope_dataset_ids,
            scope_document_ids,
            state,
        )

    (
        dataset_rag_config_template_defaults_applied_fields,
        dataset_rag_defaults_applied_fields,
        effective_rag_config,
        image_meta,
        multimodal_meta,
        rag_config_template_meta,
        scope_dataset_id,
        scope_dataset_ids,
        scope_document_ids,
        state,
    ) = await _run_preview_db_call(prepare_request)

    offload_metrics: dict[str, Any] = {}
    result = await run_blocking_retrieval_call_with_managed_session(
        lambda worker_db: run_retrieval({**state, "db": worker_db}),
        request_db=db,
        runtime_metrics=offload_metrics,
    )
    citations = result["citations"]
    metrics = dict(result["metrics"])
    query_for_retrieval = result["query_for_retrieval"].strip()

    # Ensure minimum fields exist for UI debugging.
    metrics.update(offload_metrics)
    metrics.setdefault("vector_backend", settings.VECTOR_BACKEND)
    metrics.setdefault("requested_retrieval_mode", effective_rag_config.retrieval_mode)
    metrics.setdefault("tenant_qps_quota", tenant_qps_meta)
    metrics.setdefault("multimodal_router", multimodal_meta)
    metrics.setdefault("image", image_meta)
    if dataset_rag_defaults_applied_fields:
        metrics.setdefault("dataset_rag_defaults_applied", True)
        metrics.setdefault("dataset_rag_defaults_fields", dataset_rag_defaults_applied_fields)
    if dataset_rag_config_template_defaults_applied_fields:
        metrics.setdefault("dataset_rag_config_template_defaults_applied", True)
        metrics.setdefault(
            "dataset_rag_config_template_defaults_fields",
            dataset_rag_config_template_defaults_applied_fields,
        )
    if rag_config_template_meta:
        metrics.setdefault("rag_config_template", rag_config_template_meta)
    if scope_dataset_ids:
        metrics.setdefault("scope_dataset_ids", [str(dataset_id) for dataset_id in scope_dataset_ids])

    def attach_structure(db: Session):
        structure_dataset_id = _resolve_structure_dataset_id(
            db=db, tenant_id=tenant_id, scope_dataset_id=scope_dataset_id, scope_document_ids=scope_document_ids
        )
        if body.include_structure_trace:
            _attach_document_structure_trace(
                metrics=metrics,
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=structure_dataset_id,
                citations=citations,
                max_documents=3,
                max_nodes=40,
            )

    await _run_preview_db_call(attach_structure)

    return RetrievePreviewResponse(
        query_for_retrieval=query_for_retrieval,
        citations=citations,
        metrics=metrics,
    )


@router.post("/tree-search-preview", response_model=TreeSearchPreviewResponse)
async def tree_search_preview(
    body: TreeSearchPreviewRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TreeSearchPreviewResponse:
    """
    Experimental structure-first preview.

    It reuses normal retrieval to find candidate evidence, then overlays
    document section structure for PageIndex-style explainability.
    """
    preview = await retrieve_preview(
        RetrievePreviewRequest(
            query=body.query,
            dataset_id=body.dataset_id,
            document_ids=body.document_ids,
            rag_config=body.rag_config,
            include_structure_trace=False,
        ),
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

    def build_tree_response(db: Session):
        structure_dataset_id = _resolve_structure_dataset_id(
            db=db,
            tenant_id=tenant_id,
            scope_dataset_id=body.dataset_id,
            scope_document_ids=body.document_ids,
        )
        metrics = dict(preview.metrics)
        trace = _build_document_structure_trace(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=structure_dataset_id,
            citations=preview.citations,
            max_documents=body.max_structure_docs,
            max_nodes=body.max_nodes_per_doc,
        )
        if trace:
            metrics["document_structure_trace"] = trace
        else:
            _attach_document_structure_trace(
                metrics=metrics,
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=structure_dataset_id,
                citations=preview.citations,
                max_documents=body.max_structure_docs,
                max_nodes=body.max_nodes_per_doc,
            )
        metrics.setdefault("experimental_mode", "tree_search_preview")
        metrics.setdefault("tree_search_preview_note", "structure overlay only; default retrieval mode is unchanged")
        return TreeSearchPreviewResponse(
            query=body.query,
            query_for_retrieval=preview.query_for_retrieval,
            citations=preview.citations,
            document_structures=trace["documents"] if trace else [],
            selected_sections=trace["selected_sections"] if trace else [],
            metrics=metrics,
        )

    return await _run_preview_db_call(build_tree_response)


@router.post("/image-index", include_in_schema=False)
def index_image_embeddings(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> None:
    raise HTTPException(
        status_code=410, detail={"code": "feature_retired", "message": "Local image-vector indexing has been retired"}
    )


@router.post("/image-search-preview", include_in_schema=False)
async def image_search_preview(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> None:
    raise HTTPException(
        status_code=410, detail={"code": "feature_retired", "message": "Local image-vector search has been retired"}
    )


@router.post("/prompt-preview", response_model=PromptPreviewResponse)
async def prompt_preview(
    body: PromptPreviewRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> PromptPreviewResponse:
    """Execute retrieval and return final prompt (no LLM call); for debugging prompt/context assembly."""
    t0 = time.time()
    await _run_preview_db_call(lambda worker_db: dataset_service.ensure_member(worker_db, tenant_id, account_id))

    # Best-effort per-tenant aggregate QPS limiter.
    from app.services.tenant_quota_service import enforce_tenant_qps_quota_async

    tenant_qps_meta = await enforce_tenant_qps_quota_async(tenant_id=tenant_id, key="retrieval")

    from langchain_core.prompts import ChatPromptTemplate

    from app.rag.engine import get_rag_engine
    from app.rag.pipelines.langgraph import _build_context, _build_history_text, build_rag_state
    from app.rag.retrieval.orchestrator import run_retrieval

    def prepare_request(db: Session):
        scope_dataset_id, _scope_dataset_ids, scope_document_ids = _resolve_retrieval_scope(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            document_ids=body.document_ids,
            dataset_id=body.dataset_id,
        )
        request_fields_set = body.model_fields_set
        effective_rag_config, dataset_rag_defaults_applied_fields, _dataset_defaults_meta, _rag_fields_set = (
            _resolve_dataset_defaults_rag_config(
                db=db,
                tenant_id=tenant_id,
                scope_dataset_id=scope_dataset_id,
                scope_document_ids=scope_document_ids,
                rag_config=body.rag_config,
                request_fields_set=request_fields_set,
            )
        )
        state = build_rag_state(
            question=body.query,
            history=[m.model_dump() for m in body.history],
            document_ids=scope_document_ids,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=scope_dataset_id,
            **_preview_retrieval_options(effective_rag_config),
            structured_output=body.structured_output,
            structured_preset=body.structured_preset,
            prompt_template_id=body.prompt_template_id,
            prompt_template_key=body.prompt_template_key,
            prompt_ab_experiment_key=body.prompt_ab_experiment_key,
            ab_user_key=account_id,
            db=db,
        )
        return dataset_rag_defaults_applied_fields, effective_rag_config, state

    dataset_rag_defaults_applied_fields, effective_rag_config, state = await _run_preview_db_call(prepare_request)
    offload_metrics: dict[str, Any] = {}
    retrieved = await run_blocking_retrieval_call_with_managed_session(
        lambda worker_db: run_retrieval({**state, "db": worker_db}),
        request_db=db,
        runtime_metrics=offload_metrics,
    )
    citations = retrieved["citations"]
    docs = retrieved["docs"]
    metrics = dict(retrieved["metrics"])
    metrics.update(offload_metrics)
    query_for_retrieval = retrieved["query_for_retrieval"].strip()

    def render_response(metrics: dict[str, Any]):
        ctx_t0 = time.time()
        ctx = _build_context(docs, query=query_for_retrieval or body.query)
        hist_text = _build_history_text(state["history"])
        ctx_elapsed = time.time() - ctx_t0
        format_instructions = state["format_instructions"]
        engine = get_rag_engine()
        prompt_obj = engine.prompt_template
        prompt_content = state["prompt_template_content"]
        variables: dict[str, Any] = {
            "context": ctx,
            "history": hist_text,
            "question": body.query,
            "format_instructions": format_instructions,
        }
        try:
            if prompt_content is not None:
                prompt_obj = ChatPromptTemplate.from_template(prompt_content)
            render_t0 = time.time()
            prompt_value = prompt_obj.format_prompt(**variables)
            prompt_messages = [{"type": msg.type, "content": msg.content} for msg in prompt_value.to_messages()]
            prompt_text = prompt_value.to_string()
            render_elapsed = time.time() - render_t0
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Prompt render failed: {exc}") from exc
        metrics.setdefault("vector_backend", settings.VECTOR_BACKEND)
        metrics.setdefault("requested_retrieval_mode", effective_rag_config.retrieval_mode)
        metrics.setdefault("tenant_qps_quota", tenant_qps_meta)
        if dataset_rag_defaults_applied_fields:
            metrics.setdefault("dataset_rag_defaults_applied", True)
            metrics.setdefault("dataset_rag_defaults_fields", dataset_rag_defaults_applied_fields)
        from app.rag.core.prompt_preview_metrics import compute_prompt_preview_metrics

        metrics = compute_prompt_preview_metrics(
            prompt_text=prompt_text,
            context=ctx,
            history=hist_text,
            base_metrics=metrics,
            elapsed_sec=time.time() - t0,
            context_build_elapsed_sec=ctx_elapsed,
            prompt_render_elapsed_sec=render_elapsed,
        )
        return PromptPreviewResponse(
            query_for_retrieval=query_for_retrieval,
            prompt_messages=prompt_messages,
            prompt_text=prompt_text,
            variables=variables,
            citations=citations,
            metrics=metrics,
            prompt_template_id=state["prompt_template_id"],
            prompt_template_key=state["prompt_template_key"],
            prompt_ab_experiment_key=state["prompt_ab_experiment_key"],
            prompt_ab_variant=state["prompt_ab_variant"],
        )

    return await run_blocking_in_thread(render_response, metrics)


@router.post("/retrieve", response_model=EvidenceRetrieveResponse)
async def retrieve_evidence(
    body: EvidenceRetrieveRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceRetrieveResponse:
    return await retrieve_evidence_impl(body=body, tenant_id=tenant_id, account_id=account_id, db=db)
