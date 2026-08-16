
from collections import Counter
from typing import Any


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
        counts["vector_candidates"] = int(len(vector_results or []))
        counts["colbert_candidates"] = int(colbert_candidates or 0)
        counts["colpali_candidates"] = int(len(colpali_results or []))
        counts["bm25_candidates"] = int(len(bm25_results or []))
        counts["lexical_candidates"] = int(len(lexical_results or []))
        counts["sparse_candidates"] = int(len(sparse_results or []))

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
        "effective_provider": str(
            sparse_status.get("effective_provider")
            or sparse_provider
            or "deterministic"
        ),
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
                "provider": str(
                    sparse_provider_snapshot.get("effective_provider")
                    or sparse_provider
                    or "deterministic"
                ),
                "provider_status": sparse_provider_snapshot,
            },
        }
    )
    if keyword_strategy is not None:
        keyword_strategy["bm25_used"] = bool(bm25_results)
        keyword_strategy["lexical_db_used"] = bool(lexical_results)
        keyword_strategy["sparse_used"] = bool(sparse_results)
        channel_metrics["keyword_strategy"] = keyword_strategy
