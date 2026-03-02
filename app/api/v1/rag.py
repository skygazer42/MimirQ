"""
RAG debug/preview API.

For debugging and validating:
- Retrieval parameters (top_k/threshold/mode/weight)
- Access control (tenant + account + document_ids)
"""


import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.chat import ChatRAGConfig, HistoryMessage
from app.core.config import settings
from app.core.database import get_db
from app.services.dataset_defaults import load_dataset_metadata, resolve_single_dataset_id_for_documents
from app.services.dataset_service import DatasetService
from app.services.document_access import filter_allowed_document_ids, list_accessible_document_ids
from app.services.rag_defaults import merge_rag_config_with_dataset_defaults

router = APIRouter()


class RetrievePreviewRequest(BaseModel):
    query: str = Field(min_length=1)
    history: List[HistoryMessage] = Field(default_factory=list)
    dataset_id: Optional[UUID] = None
    document_ids: List[UUID] = Field(default_factory=list)
    rag_config: ChatRAGConfig = Field(default_factory=ChatRAGConfig)


class RetrievePreviewResponse(BaseModel):
    query_for_retrieval: str
    citations: List[Dict[str, Any]]
    metrics: Dict[str, Any] = Field(default_factory=dict)


class ImageIndexRequest(BaseModel):
    dataset_id: UUID
    max_chunks: int = Field(default=3000, ge=1, le=20_000)
    upsert: bool = Field(default=True, description="Upsert into the image embedding index (overwrite existing vectors)")


class ImageIndexResponse(BaseModel):
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    dim: int = 0
    errors: List[str] = Field(default_factory=list)


class ImageSearchRequest(BaseModel):
    dataset_id: UUID
    query: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=50)
    auto_index: bool = Field(default=False, description="Best-effort: index images for the dataset before searching")


class ImageSearchResponse(BaseModel):
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)


@router.post("/retrieve-preview", response_model=RetrievePreviewResponse)
async def retrieve_preview(
    body: RetrievePreviewRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Execute retrieval only (no answer generation); for parameter tuning and retrieval quality debugging."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    scope_dataset_id: UUID | None = None
    scope_document_ids: list[UUID] = []
    if body.document_ids:
        scope_document_ids = filter_allowed_document_ids(db, tenant_id, account_id, body.document_ids)
    elif body.dataset_id:
        # Dataset-scoped retrieval without enumerating all document_ids (scales better).
        ds = DatasetService.get_dataset(db, tenant_id, body.dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)
        scope_dataset_id = body.dataset_id
    else:
        allow_open_scope = bool(getattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False))
        if not allow_open_scope:
            raise HTTPException(
                status_code=400,
                detail="dataset_id is required when document_ids is empty",
            )

    # Optional existence check (keeps behavior consistent with chat).
    if not bool(getattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True)):
        if scope_document_ids:
            pass
        elif scope_dataset_id is not None:
            from app.models.document import Document as DBDocument
            from app.services.dataset_profile_service import build_dataset_documents_query

            _ds, q = build_dataset_documents_query(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=scope_dataset_id,
            )
            q = q.filter(
                (DBDocument.status == "completed")
                | (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true")  # type: ignore[attr-defined]
            )
            exists = q.with_entities(DBDocument.id).order_by(DBDocument.updated_at.desc()).limit(1).first()
            if not exists:
                raise HTTPException(status_code=400, detail="No accessible documents for retrieval")
        else:
            exists = list_accessible_document_ids(db, tenant_id, account_id, status="completed", limit=1)
            if not exists:
                raise HTTPException(status_code=400, detail="No accessible documents for retrieval")

    from app.rag.pipelines.langgraph import build_rag_state
    from app.rag.retrieval.orchestrator import run_retrieval

    # Dataset-level default RAG config (best-effort): apply only when all docs share one dataset_id.
    #
    # For this debug endpoint, we default to a recall-first profile when the caller omits rag_config,
    # so retrieval tuning starts from a "must-recall" baseline.
    request_fields_set = set(getattr(body, "model_fields_set", set()) or set())
    rag_config_provided = "rag_config" in request_fields_set

    effective_rag_config = body.rag_config
    dataset_rag_defaults_applied_fields: list[str] = []
    rag_fields_set = set(getattr(body.rag_config, "model_fields_set", set()) or set())
    if not rag_config_provided:
        effective_rag_config = ChatRAGConfig(retrieval_profile="recall20")
        rag_fields_set = set()
    try:
        ds_id = None
        if scope_dataset_id is not None:
            ds_id = scope_dataset_id
        elif scope_document_ids:
            ds_id = resolve_single_dataset_id_for_documents(db, tenant_id=tenant_id, document_ids=scope_document_ids)
        if ds_id is not None:
            ds_meta = load_dataset_metadata(db, tenant_id=tenant_id, dataset_id=ds_id)
            raw_defaults = ds_meta.get("rag_defaults") if isinstance(ds_meta, dict) else None
            effective_rag_config, dataset_rag_defaults_applied_fields = merge_rag_config_with_dataset_defaults(
                rag_config=effective_rag_config,
                request_fields_set=rag_fields_set,
                raw_dataset_defaults=raw_defaults,
            )
    except Exception:
        dataset_rag_defaults_applied_fields = []

    state = build_rag_state(
        question=body.query,
        history=[m.model_dump() for m in body.history],
        document_ids=scope_document_ids or None,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=scope_dataset_id,
        top_k=effective_rag_config.top_k,
        score_threshold=effective_rag_config.score_threshold,
        retrieval_mode=effective_rag_config.retrieval_mode,
        retrieval_profile=effective_rag_config.retrieval_profile,
        intent_router=effective_rag_config.intent_router,
        enable_query_alias_expansion=effective_rag_config.enable_query_alias_expansion,
        query_aliases=effective_rag_config.query_aliases,
        query_alias_max_queries=effective_rag_config.query_alias_max_queries,
        enable_multi_query=effective_rag_config.enable_multi_query,
        multi_query_count=effective_rag_config.multi_query_count,
        multi_query_temperature=effective_rag_config.multi_query_temperature,
        multi_query_max_chars=effective_rag_config.multi_query_max_chars,
        alpha=effective_rag_config.alpha,
        fusion_strategy=effective_rag_config.fusion_strategy,
        fusion_budgets=effective_rag_config.fusion_budgets,
        fusion_min_scores=effective_rag_config.fusion_min_scores,
        fusion_weights=effective_rag_config.fusion_weights,
        enable_weight_rerank=effective_rag_config.enable_weight_rerank,
        vector_weight=effective_rag_config.vector_weight,
        keyword_weight=effective_rag_config.keyword_weight,
        mmr_lambda=effective_rag_config.mmr_lambda,
        enable_reranker=effective_rag_config.enable_reranker,
        reranker_provider=effective_rag_config.reranker_provider,
        reranker_top_n=effective_rag_config.reranker_top_n,
        visible_evidence_only=effective_rag_config.visible_evidence_only,
        ab_user_key=account_id,
        db=db,
    )
    # Best-effort: allow retrieval-only orchestrator to load extra evidence from DB (e.g. KG chunk injection).
    state["db"] = db

    result = run_retrieval(state) or {}
    citations = result.get("citations") or []
    metrics = result.get("metrics") or {}
    query_for_retrieval = (result.get("query_for_retrieval") or body.query or "").strip()

    # Ensure minimum fields exist for UI debugging.
    metrics = dict(metrics)
    metrics.setdefault("vector_backend", settings.VECTOR_BACKEND)
    metrics.setdefault("requested_retrieval_mode", effective_rag_config.retrieval_mode)
    if dataset_rag_defaults_applied_fields:
        metrics.setdefault("dataset_rag_defaults_applied", True)
        metrics.setdefault("dataset_rag_defaults_fields", dataset_rag_defaults_applied_fields)

    return RetrievePreviewResponse(
        query_for_retrieval=query_for_retrieval,
        citations=citations,
        metrics=metrics,
    )


@router.post("/image-index", response_model=ImageIndexResponse)
async def index_image_embeddings(
    body: ImageIndexRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Build/update the CLIP image embedding index for a dataset (best-effort).

    Security:
    - Requires dataset write permission (indexing is a compute-heavy admin action).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, body.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    from app.services.image_embedding_index import index_clip_image_embeddings_for_dataset

    stats = index_clip_image_embeddings_for_dataset(
        db=db,
        tenant_id=tenant_id,
        dataset_id=body.dataset_id,
        max_chunks=int(body.max_chunks or 0),
        upsert=bool(body.upsert),
    )
    return ImageIndexResponse(
        indexed=int(stats.indexed),
        skipped=int(stats.skipped),
        failed=int(stats.failed),
        dim=int(stats.dim),
        errors=list(stats.errors or []),
    )


@router.post("/image-search-preview", response_model=ImageSearchResponse)
async def image_search_preview(
    body: ImageSearchRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Search the image embedding index using CLIP (text -> image space).

    Notes:
    - Dataset-scoped only.
    - Returns citation-like chunk payloads (including img_id/img_url) for UI consumers.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, body.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    from app.services.image_embedding_index import (
        build_image_citations,
        index_clip_image_embeddings_for_dataset,
        search_clip_images,
    )

    indexed: int | None = None
    if bool(body.auto_index):
        # Best-effort; do not fail the search if indexing fails.
        try:
            stats = index_clip_image_embeddings_for_dataset(
                db=db,
                tenant_id=tenant_id,
                dataset_id=body.dataset_id,
                max_chunks=3000,
                upsert=True,
            )
            indexed = int(stats.indexed)
        except Exception:
            indexed = None

    hits = search_clip_images(
        db=db,
        tenant_id=tenant_id,
        dataset_id=body.dataset_id,
        query=body.query,
        top_k=int(body.top_k or 0),
    )
    citations = build_image_citations(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=body.dataset_id,
        hits=hits,
        max_items=int(body.top_k or 0),
    )
    metrics: dict[str, Any] = {"hits": int(len(citations)), "indexed": indexed}
    return ImageSearchResponse(citations=citations, metrics=metrics)


class EvidenceRetrieveRequest(BaseModel):
    """
    Production retrieval-only endpoint request.

    This is intentionally a small, stable contract for downstream systems that want to
    answer the question: "Do we have evidence for this query in the corpus?"
    """

    query: str = Field(min_length=1)
    history: List[HistoryMessage] = Field(default_factory=list)
    dataset_id: Optional[UUID] = None
    document_ids: List[UUID] = Field(default_factory=list)
    rag_config: ChatRAGConfig = Field(default_factory=ChatRAGConfig)
    # Optional deterministic seed for offline replay/regression.
    # PII-safe by construction (numeric only) and ignored by default.
    seed: Optional[int] = None


class EvidenceRetrieveResponse(BaseModel):
    schema: str = Field(default="mimirq.evidence.v1", description="Response schema identifier")
    query_for_retrieval: str
    citations: List[Dict[str, Any]]
    metrics: Dict[str, Any] = Field(default_factory=dict)
    has_evidence: bool = False
    abstain_triggered: bool = False
    abstain_reason: Optional[str] = None
    # Stable, versioned trace for downstream provenance parsing (separate from metrics/query_debug).
    retrieval_trace: Optional[Dict[str, Any]] = None
    # Optional: debug payload for query normalization/expansion (best-effort).
    query_debug: Optional[Dict[str, Any]] = None


@router.post("/retrieve", response_model=EvidenceRetrieveResponse)
async def retrieve_evidence(
    body: EvidenceRetrieveRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Execute retrieval only (no answer generation) and return evidence chunks.

    Defaults to a recall-first profile when the caller omits rag_config.
    """
    t_api_start = time.monotonic()
    DatasetService.ensure_member(db, tenant_id, account_id)

    scope_dataset_id: UUID | None = None
    scope_document_ids: list[UUID] = []
    if body.document_ids:
        scope_document_ids = filter_allowed_document_ids(db, tenant_id, account_id, body.document_ids)
    elif body.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, body.dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)
        scope_dataset_id = body.dataset_id
    else:
        allow_open_scope = bool(getattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False))
        if not allow_open_scope:
            raise HTTPException(
                status_code=400,
                detail="dataset_id is required when document_ids is empty",
            )

    # Optional existence check (keeps behavior consistent with chat).
    if not bool(getattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True)):
        if scope_document_ids:
            pass
        elif scope_dataset_id is not None:
            from app.models.document import Document as DBDocument
            from app.services.dataset_profile_service import build_dataset_documents_query

            _ds, q = build_dataset_documents_query(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=scope_dataset_id,
            )
            q = q.filter(
                (DBDocument.status == "completed")
                | (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true")  # type: ignore[attr-defined]
            )
            exists = q.with_entities(DBDocument.id).order_by(DBDocument.updated_at.desc()).limit(1).first()
            if not exists:
                raise HTTPException(status_code=400, detail="No accessible documents for retrieval")
        else:
            exists = list_accessible_document_ids(db, tenant_id, account_id, status="completed", limit=1)
            if not exists:
                raise HTTPException(status_code=400, detail="No accessible documents for retrieval")

    from app.rag.pipelines.langgraph import build_rag_state
    from app.rag.retrieval.orchestrator import run_retrieval

    # Dataset-level default RAG config (best-effort): apply only when all docs share one dataset_id.
    request_fields_set = set(getattr(body, "model_fields_set", set()) or set())
    rag_config_provided = "rag_config" in request_fields_set

    effective_rag_config = body.rag_config
    dataset_rag_defaults_applied_fields: list[str] = []
    rag_fields_set = set(getattr(body.rag_config, "model_fields_set", set()) or set())
    if not rag_config_provided:
        effective_rag_config = ChatRAGConfig(retrieval_profile="recall50")
        rag_fields_set = set()
    try:
        ds_id = None
        if scope_dataset_id is not None:
            ds_id = scope_dataset_id
        elif scope_document_ids:
            ds_id = resolve_single_dataset_id_for_documents(db, tenant_id=tenant_id, document_ids=scope_document_ids)
        if ds_id is not None:
            ds_meta = load_dataset_metadata(db, tenant_id=tenant_id, dataset_id=ds_id)
            raw_defaults = ds_meta.get("rag_defaults") if isinstance(ds_meta, dict) else None
            effective_rag_config, dataset_rag_defaults_applied_fields = merge_rag_config_with_dataset_defaults(
                rag_config=effective_rag_config,
                request_fields_set=rag_fields_set,
                raw_dataset_defaults=raw_defaults,
            )
    except Exception:
        dataset_rag_defaults_applied_fields = []

    state = build_rag_state(
        question=body.query,
        history=[m.model_dump() for m in body.history],
        document_ids=scope_document_ids or None,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=scope_dataset_id,
        top_k=effective_rag_config.top_k,
        score_threshold=effective_rag_config.score_threshold,
        retrieval_mode=effective_rag_config.retrieval_mode,
        retrieval_profile=effective_rag_config.retrieval_profile,
        intent_router=effective_rag_config.intent_router,
        enable_query_alias_expansion=effective_rag_config.enable_query_alias_expansion,
        query_aliases=effective_rag_config.query_aliases,
        query_alias_max_queries=effective_rag_config.query_alias_max_queries,
        enable_multi_query=effective_rag_config.enable_multi_query,
        multi_query_count=effective_rag_config.multi_query_count,
        multi_query_temperature=effective_rag_config.multi_query_temperature,
        multi_query_max_chars=effective_rag_config.multi_query_max_chars,
        alpha=effective_rag_config.alpha,
        fusion_strategy=effective_rag_config.fusion_strategy,
        fusion_budgets=effective_rag_config.fusion_budgets,
        fusion_min_scores=effective_rag_config.fusion_min_scores,
        fusion_weights=effective_rag_config.fusion_weights,
        enable_weight_rerank=effective_rag_config.enable_weight_rerank,
        vector_weight=effective_rag_config.vector_weight,
        keyword_weight=effective_rag_config.keyword_weight,
        mmr_lambda=effective_rag_config.mmr_lambda,
        enable_reranker=effective_rag_config.enable_reranker,
        reranker_provider=effective_rag_config.reranker_provider,
        reranker_top_n=effective_rag_config.reranker_top_n,
        visible_evidence_only=effective_rag_config.visible_evidence_only,
        ab_user_key=account_id,
        db=db,
    )
    if body.seed is not None:
        try:
            state["seed"] = int(body.seed)
        except Exception:
            # Best-effort only: seed must never break requests.
            pass
    # Best-effort: allow retrieval-only orchestrator to load extra evidence from DB (e.g. KG chunk injection).
    state["db"] = db

    primary = run_retrieval(state) or {}
    citations = primary.get("citations") or []
    metrics = dict(primary.get("metrics") or {})
    query_for_retrieval = (primary.get("query_for_retrieval") or body.query or "").strip()
    query_debug = primary.get("query_debug")
    if not isinstance(query_debug, dict):
        query_debug = None

    # Ensure minimum fields exist for downstream debugging.
    metrics.setdefault("vector_backend", settings.VECTOR_BACKEND)
    metrics.setdefault("requested_retrieval_mode", effective_rag_config.retrieval_mode)
    if dataset_rag_defaults_applied_fields:
        metrics.setdefault("dataset_rag_defaults_applied", True)
        metrics.setdefault("dataset_rag_defaults_fields", dataset_rag_defaults_applied_fields)

    abstain_triggered = bool(primary.get("abstain_triggered") or metrics.get("abstain_triggered") or False)
    abstain_reason = primary.get("abstain_reason") or metrics.get("abstain_reason") or None
    has_evidence = bool(citations) and not abstain_triggered

    selected_pass = "primary"
    fallback: dict[str, Any] | None = None

    # Optional: iterative fallback for evidence discovery.
    try:
        iterative_enabled = bool(getattr(settings, "EVIDENCE_ITERATIVE_RETRIEVE_ENABLED", False))
        max_passes = max(1, int(getattr(settings, "EVIDENCE_ITERATIVE_RETRIEVE_MAX_PASSES", 2) or 2))
    except Exception:
        iterative_enabled = False
        max_passes = 1

    iterative_summary: dict[str, Any] | None = None
    if iterative_enabled and max_passes >= 2 and not has_evidence:
        from app.rag.core.text import normalize_retrieval_mode  # avoid import cycles at module import

        # Pass 2: switch to a more recall-friendly setup.
        fallback_profile = str(getattr(settings, "EVIDENCE_ITERATIVE_RETRIEVE_FALLBACK_PROFILE", "coverage80") or "coverage80").strip().lower()
        if fallback_profile not in {"recall20", "recall50", "coverage80"}:
            fallback_profile = "coverage80"

        # Default fallback mode is keyword; allow override, but keep it safe.
        fallback_mode = str(getattr(settings, "EVIDENCE_ITERATIVE_RETRIEVE_FALLBACK_MODE", "keyword") or "keyword").strip().lower()
        fallback_mode = normalize_retrieval_mode(fallback_mode)
        if fallback_mode not in {"hybrid", "vector", "keyword", "mmr"}:
            fallback_mode = "keyword"

        # Ensure the profile's top_k contract holds on the final slice as well.
        try:
            base_k = int(state.get("top_k") or 0)
        except Exception:
            base_k = 0
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

        fallback = run_retrieval(fallback_state) or {}
        f_citations = fallback.get("citations") or []
        f_metrics = dict(fallback.get("metrics") or {})
        f_abstain = bool(fallback.get("abstain_triggered") or f_metrics.get("abstain_triggered") or False)
        f_has_evidence = bool(f_citations) and not f_abstain

        def _top_score(m: dict[str, Any]) -> float:
            raw = m.get("top_relevance_score")
            try:
                return float(raw) if raw is not None else 0.0
            except Exception:
                return 0.0

        p_top = _top_score(metrics)
        f_top = _top_score(f_metrics)

        p_n = len(citations) if isinstance(citations, list) else 0
        f_n = len(f_citations) if isinstance(f_citations, list) else 0

        # Selection: prefer a pass that clears abstain/has evidence; else prefer higher top score / more citations.
        use_fallback = False
        if f_has_evidence and not has_evidence:
            use_fallback = True
        elif f_has_evidence and has_evidence:
            use_fallback = f_top > p_top
        elif (not f_has_evidence) and (not has_evidence):
            use_fallback = (f_top > p_top) or (f_top == p_top and f_n > p_n)

        iterative_summary = {
            "enabled": True,
            "max_passes": int(max_passes),
            "selected_pass": "fallback" if use_fallback else "primary",
            "passes": [
                {
                    "pass": "primary",
                    "retrieval_mode": str(metrics.get("retrieval_mode") or ""),
                    "retrieval_profile": str(state.get("retrieval_profile") or "") or None,
                    "empty_retrieval": (metrics.get("empty_retrieval") if isinstance(metrics.get("empty_retrieval"), dict) else None),
                    "citations": int(p_n),
                    "top_relevance_score": round(float(p_top), 3),
                    "abstain_triggered": bool(abstain_triggered),
                    "has_evidence": bool(has_evidence),
                    "retrieval_elapsed_sec": float(metrics.get("retrieval_elapsed_sec") or 0.0),
                },
                {
                    "pass": "fallback",
                    "retrieval_mode": str(f_metrics.get("retrieval_mode") or ""),
                    "retrieval_profile": str(fallback_profile),
                    "empty_retrieval": (f_metrics.get("empty_retrieval") if isinstance(f_metrics.get("empty_retrieval"), dict) else None),
                    "citations": int(f_n),
                    "top_relevance_score": round(float(f_top), 3),
                    "abstain_triggered": bool(f_abstain),
                    "has_evidence": bool(f_has_evidence),
                    "retrieval_elapsed_sec": float(f_metrics.get("retrieval_elapsed_sec") or 0.0),
                },
            ],
        }

        if use_fallback:
            selected_pass = "fallback"
            citations = f_citations
            metrics = f_metrics
            query_for_retrieval = (fallback.get("query_for_retrieval") or query_for_retrieval or "").strip()
            qd = fallback.get("query_debug")
            query_debug = qd if isinstance(qd, dict) else query_debug
            abstain_triggered = bool(f_abstain)
            abstain_reason = fallback.get("abstain_reason") or f_metrics.get("abstain_reason") or None
            has_evidence = bool(f_has_evidence)

    # Optional strictness: if configured, require the top relevance score to clear the threshold.
    # This is a lightweight guardrail for "does the corpus contain this?" style calls.
    min_top_rel = float(getattr(settings, "RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE", 0.0) or 0.0)
    if has_evidence and min_top_rel > 0.0:
        top_rel_raw = metrics.get("top_relevance_score")
        try:
            top_rel = float(top_rel_raw) if top_rel_raw is not None else None
        except Exception:
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
            except Exception:
                top_rel = None
        if top_rel is not None and top_rel < min_top_rel:
            has_evidence = False

    if iterative_summary and isinstance(iterative_summary, dict):
        metrics.setdefault("iterative_retrieve", iterative_summary)
        if isinstance(query_debug, dict):
            query_debug.setdefault("iterative_retrieve", iterative_summary)

    # Prometheus metrics (optional; no-op when disabled).
    try:
        from app.rag.retrieval.metrics import observe_evidence_retrieve

        top_rel = 0.0
        try:
            top_rel = float(metrics.get("top_relevance_score") or 0.0)
        except Exception:
            top_rel = 0.0
        observe_evidence_retrieve(
            duration_sec=(time.monotonic() - t_api_start),
            has_evidence=bool(has_evidence),
            abstain_triggered=bool(abstain_triggered),
            retrieval_mode=str(metrics.get("retrieval_mode") or effective_rag_config.retrieval_mode or ""),
            selected_pass=str(selected_pass),
            citations_count=(len(citations) if isinstance(citations, list) else 0),
            top_relevance_score=float(top_rel or 0.0),
        )
    except Exception:
        # Metrics are best-effort; never fail the API due to observability.
        pass

    # Stable, versioned retrieval trace (separate from metrics/query_debug).
    retrieval_trace_payload: dict[str, Any] | None = None
    try:
        passes: list[dict[str, Any]] = []
        primary_trace = primary.get("retrieval_trace")
        if isinstance(primary_trace, dict):
            passes.append({"pass": "primary", "trace": primary_trace})
        fallback_trace = (fallback or {}).get("retrieval_trace") if isinstance(fallback, dict) else None
        if isinstance(fallback_trace, dict):
            passes.append({"pass": "fallback", "trace": fallback_trace})

        if passes:
            retrieval_trace_payload = {
                "schema": "mimirq.retrieval_trace.v1",
                "selected_pass": str(selected_pass),
                "passes": passes,
            }
    except Exception:
        retrieval_trace_payload = None

    return EvidenceRetrieveResponse(
        query_for_retrieval=query_for_retrieval,
        citations=citations,
        metrics=metrics,
        has_evidence=has_evidence,
        abstain_triggered=abstain_triggered,
        abstain_reason=abstain_reason,
        retrieval_trace=retrieval_trace_payload,
        query_debug=query_debug,
    )


class PromptPreviewRequest(BaseModel):
    query: str = Field(min_length=1)
    history: List[HistoryMessage] = Field(default_factory=list)
    dataset_id: Optional[UUID] = None
    document_ids: List[UUID] = Field(default_factory=list)
    rag_config: ChatRAGConfig = Field(default_factory=ChatRAGConfig)
    structured_output: bool = False
    structured_preset: Optional[str] = None
    prompt_template_id: Optional[UUID] = None
    prompt_template_key: Optional[str] = None
    prompt_ab_experiment_key: Optional[str] = None


class PromptPreviewResponse(BaseModel):
    query_for_retrieval: str
    prompt_messages: List[Dict[str, Any]]
    prompt_text: str
    variables: Dict[str, Any]
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    prompt_template_id: Optional[str] = None
    prompt_template_key: Optional[str] = None
    prompt_ab_experiment_key: Optional[str] = None
    prompt_ab_variant: Optional[str] = None


@router.post("/prompt-preview", response_model=PromptPreviewResponse)
async def prompt_preview(
    body: PromptPreviewRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Execute retrieval and return final prompt (no LLM call); for debugging prompt/context assembly."""
    t0 = time.time()
    DatasetService.ensure_member(db, tenant_id, account_id)

    scope_dataset_id: UUID | None = None
    scope_document_ids: list[UUID] = []
    if body.document_ids:
        scope_document_ids = filter_allowed_document_ids(db, tenant_id, account_id, body.document_ids)
    elif body.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, body.dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)
        scope_dataset_id = body.dataset_id
    else:
        allow_open_scope = bool(getattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False))
        if not allow_open_scope:
            raise HTTPException(
                status_code=400,
                detail="dataset_id is required when document_ids is empty",
            )

    if not bool(getattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True)):
        if scope_document_ids:
            pass
        elif scope_dataset_id is not None:
            from app.models.document import Document as DBDocument
            from app.services.dataset_profile_service import build_dataset_documents_query

            _ds, q = build_dataset_documents_query(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=scope_dataset_id,
            )
            q = q.filter(
                (DBDocument.status == "completed")
                | (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true")  # type: ignore[attr-defined]
            )
            exists = q.with_entities(DBDocument.id).order_by(DBDocument.updated_at.desc()).limit(1).first()
            if not exists:
                raise HTTPException(status_code=400, detail="No accessible documents for retrieval")
        else:
            exists = list_accessible_document_ids(db, tenant_id, account_id, status="completed", limit=1)
            if not exists:
                raise HTTPException(status_code=400, detail="No accessible documents for retrieval")

    # Dataset-level default RAG config (best-effort): apply only when all docs share one dataset_id.
    effective_rag_config = body.rag_config
    dataset_rag_defaults_applied_fields: list[str] = []
    rag_fields_set = set(getattr(body.rag_config, "model_fields_set", set()) or set())
    if "rag_config" not in set(getattr(body, "model_fields_set", set()) or set()):
        rag_fields_set = set()
    try:
        ds_id = None
        if scope_dataset_id is not None:
            ds_id = scope_dataset_id
        elif scope_document_ids:
            ds_id = resolve_single_dataset_id_for_documents(db, tenant_id=tenant_id, document_ids=scope_document_ids)
        if ds_id is not None:
            ds_meta = load_dataset_metadata(db, tenant_id=tenant_id, dataset_id=ds_id)
            raw_defaults = ds_meta.get("rag_defaults") if isinstance(ds_meta, dict) else None
            effective_rag_config, dataset_rag_defaults_applied_fields = merge_rag_config_with_dataset_defaults(
                rag_config=effective_rag_config,
                request_fields_set=rag_fields_set,
                raw_dataset_defaults=raw_defaults,
            )
    except Exception:
        dataset_rag_defaults_applied_fields = []

    from langchain_core.prompts import ChatPromptTemplate

    from app.rag.engine import get_rag_engine
    from app.rag.pipelines.langgraph import _build_context, _build_history_text, build_rag_state
    from app.rag.retrieval.orchestrator import run_retrieval

    state = build_rag_state(
        question=body.query,
        history=[m.model_dump() for m in body.history],
        document_ids=scope_document_ids or None,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=scope_dataset_id,
        top_k=effective_rag_config.top_k,
        score_threshold=effective_rag_config.score_threshold,
        retrieval_mode=effective_rag_config.retrieval_mode,
        retrieval_profile=effective_rag_config.retrieval_profile,
        intent_router=effective_rag_config.intent_router,
        enable_query_alias_expansion=effective_rag_config.enable_query_alias_expansion,
        query_aliases=effective_rag_config.query_aliases,
        query_alias_max_queries=effective_rag_config.query_alias_max_queries,
        enable_multi_query=effective_rag_config.enable_multi_query,
        multi_query_count=effective_rag_config.multi_query_count,
        multi_query_temperature=effective_rag_config.multi_query_temperature,
        multi_query_max_chars=effective_rag_config.multi_query_max_chars,
        alpha=effective_rag_config.alpha,
        fusion_strategy=effective_rag_config.fusion_strategy,
        fusion_budgets=effective_rag_config.fusion_budgets,
        fusion_min_scores=effective_rag_config.fusion_min_scores,
        fusion_weights=effective_rag_config.fusion_weights,
        enable_weight_rerank=effective_rag_config.enable_weight_rerank,
        vector_weight=effective_rag_config.vector_weight,
        keyword_weight=effective_rag_config.keyword_weight,
        mmr_lambda=effective_rag_config.mmr_lambda,
        enable_reranker=effective_rag_config.enable_reranker,
        reranker_provider=effective_rag_config.reranker_provider,
        reranker_top_n=effective_rag_config.reranker_top_n,
        visible_evidence_only=effective_rag_config.visible_evidence_only,
        structured_output=body.structured_output,
        structured_preset=body.structured_preset,
        prompt_template_id=body.prompt_template_id,
        prompt_template_key=body.prompt_template_key,
        prompt_ab_experiment_key=body.prompt_ab_experiment_key,
        ab_user_key=account_id,
        db=db,
    )
    # Best-effort: allow retrieval-only orchestrator to load extra evidence from DB (e.g. KG chunk injection).
    state["db"] = db

    retrieved = run_retrieval(state) or {}
    citations = retrieved.get("citations") or []
    docs = retrieved.get("docs") or []
    metrics = dict(retrieved.get("metrics") or {})
    query_for_retrieval = (retrieved.get("query_for_retrieval") or body.query or "").strip()

    ctx_t0 = time.time()
    ctx = _build_context(docs, query=query_for_retrieval or body.query)
    hist_text = _build_history_text(state.get("history"))
    ctx_elapsed = time.time() - ctx_t0
    format_instructions = state.get("format_instructions") or ""

    engine = get_rag_engine()
    prompt_obj = engine.prompt_template
    prompt_content = state.get("prompt_template_content")
    if prompt_content:
        try:
            prompt_obj = ChatPromptTemplate.from_template(str(prompt_content))
        except Exception:
            prompt_obj = engine.prompt_template

    variables: Dict[str, Any] = {
        "context": ctx,
        "history": hist_text,
        "question": body.query,
        "format_instructions": format_instructions,
    }

    try:
        render_t0 = time.time()
        prompt_value = prompt_obj.format_prompt(**variables)
        prompt_messages = []
        for msg in prompt_value.to_messages():
            prompt_messages.append(
                {
                    "type": getattr(msg, "type", msg.__class__.__name__),
                    "content": getattr(msg, "content", None),
                }
            )
        prompt_text = prompt_value.to_string()
        render_elapsed = time.time() - render_t0
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Prompt render failed: {exc}") from exc

    metrics.setdefault("vector_backend", settings.VECTOR_BACKEND)
    metrics.setdefault("requested_retrieval_mode", effective_rag_config.retrieval_mode)
    if dataset_rag_defaults_applied_fields:
        metrics.setdefault("dataset_rag_defaults_applied", True)
        metrics.setdefault("dataset_rag_defaults_fields", dataset_rag_defaults_applied_fields)

    from app.rag.core.prompt_preview_metrics import compute_prompt_preview_metrics

    metrics = compute_prompt_preview_metrics(
        prompt_text=prompt_text,
        context=ctx,
        history=hist_text,
        base_metrics=metrics,
        elapsed_sec=(time.time() - t0),
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
        prompt_template_id=state.get("prompt_template_id"),
        prompt_template_key=state.get("prompt_template_key"),
        prompt_ab_experiment_key=state.get("prompt_ab_experiment_key"),
        prompt_ab_variant=state.get("prompt_ab_variant"),
    )
