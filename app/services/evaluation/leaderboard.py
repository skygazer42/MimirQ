"""
Regression leaderboard helpers (best-effort).

Goal:
- Provide a simple, PII-safe way to rank and compare regression runs by a metric key.
- Attach a stable retrieval_config_hash so downstream dashboards can group runs by config.
"""

import math
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from app.infrastructure.config import settings
from app.rag.llm.prompts.query_rewrite import build_query_rewrite_strategy_spec
from app.rag.retrieval.configuration.fingerprint import build_retrieval_config_fingerprint

if TYPE_CHECKING:
    from app.models.evaluation.results import RagasRegressionRun


def _to_float(v: Any) -> float | None:
    try:
        number = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _safe_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _build_run_retrieval_config_hash(*, rag_params: dict[str, Any]) -> str:
    rp = rag_params
    mode = str(rp.get("retrieval_mode") or "").strip().lower() or "hybrid"

    rewrite_enabled = bool(settings.ENABLE_QUERY_REWRITE)
    rewrite_strategy_id: str | None = None
    rewrite_strategy_hash: str | None = None
    rewrite_temp: float | None = None
    rewrite_max_chars: int | None = None
    if rewrite_enabled:
        spec = build_query_rewrite_strategy_spec(settings.QUERY_REWRITE_STRATEGY)
        rewrite_strategy_id = spec["strategy_id"]
        rewrite_strategy_hash = spec["strategy_hash"]
        try:
            rewrite_temp = float(settings.QUERY_REWRITE_TEMPERATURE or 0.0)
        except Exception:
            rewrite_temp = 0.0
        try:
            rewrite_max_chars = int(settings.QUERY_REWRITE_MAX_CHARS or 0)
        except Exception:
            rewrite_max_chars = 0

    fp = build_retrieval_config_fingerprint(
        config={
            "requested_retrieval_mode": mode,
            "retrieval_mode": mode,
            "retrieval_mode_auto_routed": False,
            "retrieval_profile": None,
            "top_k": rp.get("top_k"),
            "score_threshold": _to_float(rp.get("score_threshold")) or 0.0,
            "alpha": _to_float(rp.get("alpha")) or 0.0,
            "fusion_strategy": str(settings.RETRIEVAL_FUSION_STRATEGY or "linear"),
            "fusion_budgets": None,
            "fusion_min_scores": None,
            "enable_weight_rerank": bool(rp.get("enable_weight_rerank", True)),
            "vector_weight": _to_float(rp.get("vector_weight")) or 0.0,
            "keyword_weight": _to_float(rp.get("keyword_weight")) or 0.0,
            "mmr_lambda": _to_float(rp.get("mmr_lambda")) or 0.0,
            "enable_reranker": bool(rp.get("enable_reranker", False)),
            "reranker_provider": str(rp.get("reranker_provider") or ""),
            "reranker_top_n": int(rp.get("reranker_top_n") or 0),
            "visible_evidence_only": False,
            "vector_backend": settings.VECTOR_BACKEND,
            "bm25_enabled": bool(settings.BM25_INDEX_ENABLED),
            "lexical_enabled": bool(settings.LEXICAL_DB_TRGM_ENABLED),
            "parent_child_auto_merge_enabled": bool(settings.RAG_PARENT_CHILD_AUTO_MERGE_ENABLED),
            "parent_child_auto_merge_mode": settings.RAG_PARENT_CHILD_AUTO_MERGE_MODE,
            "kg_query_expansion_enabled": bool(settings.RAG_KG_QUERY_EXPANSION_ENABLED),
            "kg_chunk_injection_enabled": bool(settings.RAG_KG_CHUNK_INJECTION_ENABLED),
            "evidence_post_rerank_enabled": bool(settings.EVIDENCE_POST_RERANK_ENABLED),
            "evidence_post_rerank_provider": settings.EVIDENCE_POST_RERANK_PROVIDER,
            "evidence_post_rerank_top_n": int(settings.EVIDENCE_POST_RERANK_TOP_N or 0),
            "evidence_post_rerank_pipeline_enabled": bool(settings.EVIDENCE_POST_RERANK_PIPELINE_ENABLED),
            "evidence_post_rerank_pipeline": [stage.model_dump() for stage in settings.EVIDENCE_POST_RERANK_PIPELINE],
            "query_rewrite": {
                "enabled": bool(rewrite_enabled),
                "strategy_id": rewrite_strategy_id if rewrite_enabled else None,
                "strategy_hash": rewrite_strategy_hash if rewrite_enabled else None,
                "temperature": rewrite_temp if rewrite_enabled else None,
                "max_chars": int(rewrite_max_chars or 0) if rewrite_enabled else None,
            },
        }
    )
    return fp["hash"]


def build_regression_run_leaderboard(
    *,
    runs: "Iterable[RagasRegressionRun]",
    metric_key: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Build a leaderboard-like list sorted by `metric_key` (descending).

    The function is intentionally tolerant of partially-populated run rows.
    """
    metric_key = metric_key.strip() or "retrieval_mrr"
    limit = max(1, min(int(limit or 0), 500))

    items: list[dict[str, Any]] = []
    for r in runs:
        summary = _safe_dict(r.summary)
        params = _safe_dict(r.params)
        rag_params = _safe_dict(params.get("rag_params"))

        metric_value = _to_float(summary.get(metric_key))
        cfg_hash = _build_run_retrieval_config_hash(rag_params=rag_params) if rag_params else None

        items.append(
            {
                "run_id": str(r.id),
                "status": r.status,
                "created_at": r.created_at,
                "finished_at": r.finished_at,
                "metric_key": metric_key,
                "metric_value": metric_value,
                "retrieval_config_hash": cfg_hash,
            }
        )

    # Sort: higher is better; missing metrics go last.
    items.sort(key=lambda item: (item["metric_value"] is None, -(item["metric_value"] or 0.0)))
    return items[:limit]


__all__ = ["build_regression_run_leaderboard"]
