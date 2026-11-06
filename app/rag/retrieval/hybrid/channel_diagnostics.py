from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from app.core.config import settings

if TYPE_CHECKING:
    from app.rag.retrieval.hybrid.candidate_ranking import FusionPolicy
    from app.rag.retrieval.hybrid.channel_collection import ChannelCollection, ChannelPolicy, ChannelRequest
    from app.rag.retrieval.hybrid.channel_results import HybridChannelResults


def empty_channel_metrics() -> dict[str, Any]:
    return {
        "timing": {"vector_ms": 0.0, "colbert_ms": 0.0, "bm25_ms": 0.0, "lexical_ms": 0.0, "fusion_ms": 0.0},
        "counts": {
            "vector_candidates": 0,
            "colbert_candidates": 0,
            "colpali_candidates": 0,
            "bm25_candidates": 0,
            "lexical_candidates": 0,
            "sparse_candidates": 0,
        },
        "retrieval_degraded": False,
        "degraded_reasons": [],
        "all_retrieval_channels_failed": False,
    }


def update_hybrid_channel_diagnostics(
    *,
    channel_metrics: dict[str, Any],
    vector_results: list[dict[str, Any]],
    bm25_results: list[dict[str, Any]],
    lexical_results: list[dict[str, Any]],
    sparse_results: list[dict[str, Any]],
    colpali_results: list[dict[str, Any]],
    vector_elapsed_ms: float,
    colbert_elapsed_ms: float,
    bm25_elapsed_ms: float,
    lexical_elapsed_ms: float,
    colbert_candidates: int,
    colbert_used: bool,
    colbert_retrieval_enabled: bool,
    colbert_provider: str,
    retrieval_mode: str,
    fusion_strategy: str,
    rrf_k: int,
    fusion_weights: dict[str, float] | None,
    vector_backend: str,
    want_vector: bool,
    want_bm25: bool,
    want_lexical: bool,
    want_sparse: bool,
    want_colpali: bool,
    vector_filter_applied: bool,
    bm25_filter_applied: bool,
    bm25_index_enabled: bool,
    last_bm25_status: dict[str, Any],
    lexical_run_reason: str,
    lexical_hybrid_fallback_only: bool,
    lexical_db_enabled: bool,
    lexical_db_fts_config: str,
    lexical_db_trgm_enabled: bool,
    lexical_pg_trgm_available: bool | None,
    metadata_exact_pre_fusion_stats: dict[str, Any],
    colpali_reason: str,
    sparse_provider_status: dict[str, Any],
    sparse_provider: str,
    keyword_strategy: dict[str, Any] | None,
) -> None:
    lexical_methods: Counter[str] = Counter()
    for result in lexical_results:
        meta = result.get("metadata") or {}
        method = str(meta.get("lexical_method") or "unknown").strip().lower() or "unknown"
        lexical_methods[method] += 1

    timing = channel_metrics.get("timing")
    if isinstance(timing, dict):
        timing["vector_ms"] = round(float(vector_elapsed_ms), 2)
        timing["colbert_ms"] = round(float(colbert_elapsed_ms), 2)
        timing["bm25_ms"] = round(float(bm25_elapsed_ms), 2)
        timing["lexical_ms"] = round(float(lexical_elapsed_ms), 2)

    counts = channel_metrics.get("counts")
    if isinstance(counts, dict):
        counts["vector_candidates"] = len(vector_results or [])
        counts["colbert_candidates"] = int(colbert_candidates or 0)
        counts["colpali_candidates"] = len(colpali_results or [])
        counts["bm25_candidates"] = len(bm25_results or [])
        counts["lexical_candidates"] = len(lexical_results or [])
        counts["sparse_candidates"] = len(sparse_results or [])

    colbert_box = channel_metrics.get("colbert_ann")
    if not isinstance(colbert_box, dict):
        colbert_box = {}
    colbert_readiness = colbert_box.get("readiness") if isinstance(colbert_box.get("readiness"), dict) else {}
    colbert_box.update(
        {
            "enabled": bool(colbert_retrieval_enabled),
            "used": bool(colbert_used),
            "candidates": int(colbert_candidates or 0),
            "provider": str(
                (colbert_readiness.get("effective_provider") if isinstance(colbert_readiness, dict) else None)
                or colbert_provider
                or ""
            ),
        }
    )
    channel_metrics["colbert_ann"] = colbert_box

    sparse_status = dict(sparse_provider_status or {})
    sparse_provider_snapshot = {
        "requested_provider": str(sparse_status.get("requested_provider") or ""),
        "requested_provider_normalized": str(sparse_status.get("requested_provider_normalized") or ""),
        "effective_provider": str(sparse_status.get("effective_provider") or sparse_provider or "deterministic"),
        "provider_supported": bool(sparse_status.get("provider_supported", False)),
        "model_required": bool(sparse_status.get("model_required", False)),
        "model_configured": bool(sparse_status.get("model_configured", False)),
        "status": str(sparse_status.get("status") or ""),
        "reason": str(sparse_status.get("reason") or ""),
        "outcome": str(sparse_status.get("outcome") or ""),
    }

    channel_metrics.update(
        {
            "retrieval_mode": retrieval_mode,
            "fusion_strategy": fusion_strategy,
            "rrf_k": int(rrf_k or 0),
            "fusion_weights": (
                dict(
                    sorted(
                        (str(key), round(float(value), 6))
                        for key, value in (fusion_weights or {}).items()
                        if str(key or "").strip() and value is not None
                    )
                )
                if isinstance(fusion_weights, dict) and fusion_weights
                else None
            ),
            "vector_backend": vector_backend,
            "vector": {
                "enabled": bool(want_vector),
                "candidates": len(vector_results or []),
                "filter_applied": bool(vector_filter_applied),
            },
            "bm25": {
                "enabled": bool(want_bm25),
                "candidates": len(bm25_results or []),
                "index_enabled": bool(bm25_index_enabled),
                "filter_applied": bool(bm25_filter_applied),
                "status": dict(last_bm25_status or {}),
            },
            "lexical_db": {
                "enabled": bool(want_lexical) and bool(lexical_db_enabled),
                "used": bool(lexical_results),
                "candidates": len(lexical_results or []),
                "run_reason": lexical_run_reason,
                "hybrid_fallback_only": bool(lexical_hybrid_fallback_only),
                "fts_config": lexical_db_fts_config,
                "trgm_enabled": bool(lexical_db_trgm_enabled),
                "pg_trgm_available": lexical_pg_trgm_available,
                "methods": dict(lexical_methods),
            },
            "metadata_exact_pre_fusion": dict(metadata_exact_pre_fusion_stats),
            "colpali": {
                "enabled": bool(want_colpali),
                "used": bool(colpali_results),
                "candidates": len(colpali_results or []),
                "reason": colpali_reason,
            },
            "sparse": {
                "enabled": bool(want_sparse),
                "candidates": len(sparse_results or []),
                "provider": str(sparse_provider_snapshot["effective_provider"] or sparse_provider or "deterministic"),
                "provider_status": sparse_provider_snapshot,
            },
        }
    )
    if keyword_strategy is not None:
        keyword_strategy["bm25_used"] = bool(bm25_results)
        keyword_strategy["lexical_db_used"] = bool(lexical_results)
        keyword_strategy["sparse_used"] = bool(sparse_results)
        channel_metrics["keyword_strategy"] = keyword_strategy


def serialize_collected_channels(
    request: ChannelRequest,
    collection: ChannelCollection,
    *,
    policy: ChannelPolicy,
    fusion: FusionPolicy,
    channels: HybridChannelResults,
) -> dict[str, Any]:
    metrics = empty_channel_metrics()
    colbert = collection.vector.colbert
    update_hybrid_channel_diagnostics(
        channel_metrics=metrics,
        vector_results=channels.vector_results,
        bm25_results=channels.bm25_results,
        lexical_results=channels.lexical_results,
        sparse_results=channels.sparse_results,
        colpali_results=collection.auxiliary.colpali_records,
        vector_elapsed_ms=collection.vector.elapsed_ms,
        colbert_elapsed_ms=collection.vector.colbert_elapsed_ms,
        bm25_elapsed_ms=collection.keyword.bm25_elapsed_ms,
        lexical_elapsed_ms=collection.keyword.lexical_elapsed_ms,
        colbert_candidates=len(colbert.records) if colbert is not None else 0,
        colbert_used=bool(colbert and colbert.records),
        colbert_retrieval_enabled=settings.COLBERT_RETRIEVAL_ENABLED,
        colbert_provider=settings.COLBERT_RETRIEVAL_PROVIDER,
        retrieval_mode=request.mode,
        fusion_strategy=fusion.strategy,
        rrf_k=fusion.rrf_k,
        fusion_weights=fusion.weights,
        vector_backend=settings.VECTOR_BACKEND,
        want_vector=collection.plan.vector,
        want_bm25=collection.plan.bm25,
        want_lexical=collection.plan.lexical,
        want_sparse=collection.plan.sparse,
        want_colpali=collection.plan.colpali,
        vector_filter_applied=bool(request.resolved_scope.vector_filter),
        bm25_filter_applied=bool(request.resolved_scope.keyword_filter),
        bm25_index_enabled=policy.bm25_enabled,
        last_bm25_status=collection.keyword.bm25.status,
        lexical_run_reason=collection.keyword.lexical_run_reason,
        lexical_hybrid_fallback_only=policy.lexical_hybrid_fallback_only,
        lexical_db_enabled=policy.lexical_enabled,
        lexical_db_fts_config=settings.LEXICAL_DB_FTS_CONFIG,
        lexical_db_trgm_enabled=settings.LEXICAL_DB_TRGM_ENABLED,
        lexical_pg_trgm_available=policy.pg_trgm_available,
        metadata_exact_pre_fusion_stats=channels.metadata_exact_pre_fusion_stats,
        colpali_reason=collection.plan.colpali_reason,
        sparse_provider_status=collection.auxiliary.sparse.status,
        sparse_provider=policy.sparse.provider,
        keyword_strategy=collection.plan.keyword_strategy,
    )
    collection.health.publish(metrics)
    return metrics
