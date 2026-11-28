from collections import Counter
from typing import TYPE_CHECKING, Any

from app.infrastructure.config import settings

if TYPE_CHECKING:
    from app.rag.retrieval.ranking.candidates import FusionPolicy
    from app.rag.retrieval.recall.channel_collection import ChannelCollection, ChannelPolicy, ChannelRequest
    from app.rag.retrieval.recall.results import HybridChannelResults


def empty_channel_metrics() -> dict[str, Any]:
    return {
        "timing": {"vector_ms": 0.0, "bm25_ms": 0.0, "lexical_ms": 0.0, "fusion_ms": 0.0},
        "counts": {
            "vector_candidates": 0,
            "bm25_candidates": 0,
            "lexical_candidates": 0,
        },
        "retrieval_degraded": False,
        "degraded_reasons": [],
        "all_retrieval_channels_failed": False,
    }


def serialize_collected_channels(
    request: "ChannelRequest",
    collection: "ChannelCollection",
    *,
    policy: "ChannelPolicy",
    fusion: "FusionPolicy",
    channels: "HybridChannelResults",
) -> dict[str, Any]:
    metrics = empty_channel_metrics()
    lexical_methods: Counter[str] = Counter()
    for result in channels.lexical_results:
        meta = result.get("metadata") or {}
        method = str(meta.get("lexical_method") or "unknown").strip().lower() or "unknown"
        lexical_methods[method] += 1

    metrics["timing"].update(
        {
            "vector_ms": round(float(collection.vector.elapsed_ms), 2),
            "bm25_ms": round(float(collection.keyword.bm25_elapsed_ms), 2),
            "lexical_ms": round(float(collection.keyword.lexical_elapsed_ms), 2),
        }
    )
    metrics["counts"].update(
        {
            "vector_candidates": len(channels.vector_results),
            "bm25_candidates": len(channels.bm25_results),
            "lexical_candidates": len(channels.lexical_results),
        }
    )
    metrics.update(
        {
            "retrieval_mode": request.mode,
            "fusion_strategy": fusion.strategy,
            "rrf_k": fusion.rrf_k,
            "fusion_weights": (
                dict(
                    sorted(
                        (str(key), round(float(value), 6))
                        for key, value in fusion.weights.items()
                        if key.strip() and value is not None
                    )
                )
                if fusion.weights
                else None
            ),
            "vector_backend": settings.VECTOR_BACKEND,
            "vector": {
                "enabled": bool(collection.plan.vector),
                "candidates": len(channels.vector_results),
                "filter_applied": bool(request.resolved_scope.vector_filter),
            },
            "bm25": {
                "enabled": bool(collection.plan.bm25),
                "candidates": len(channels.bm25_results),
                "index_enabled": bool(policy.bm25_enabled),
                "filter_applied": bool(request.resolved_scope.keyword_filter),
                "status": dict(collection.keyword.bm25.status),
            },
            "lexical_db": {
                "enabled": bool(collection.plan.lexical) and bool(policy.lexical_enabled),
                "used": bool(channels.lexical_results),
                "candidates": len(channels.lexical_results),
                "run_reason": collection.keyword.lexical_run_reason,
                "hybrid_fallback_only": bool(policy.lexical_hybrid_fallback_only),
                "fts_config": settings.LEXICAL_DB_FTS_CONFIG,
                "trgm_enabled": bool(settings.LEXICAL_DB_TRGM_ENABLED),
                "pg_trgm_available": policy.pg_trgm_available,
                "methods": dict(lexical_methods),
            },
            "metadata_exact_pre_fusion": dict(channels.metadata_exact_pre_fusion_stats),
        }
    )
    keyword_strategy = collection.plan.keyword_strategy
    if keyword_strategy is not None:
        keyword_strategy["bm25_used"] = bool(channels.bm25_results)
        keyword_strategy["lexical_db_used"] = bool(channels.lexical_results)
        metrics["keyword_strategy"] = keyword_strategy
    collection.health.publish(metrics)
    return metrics
