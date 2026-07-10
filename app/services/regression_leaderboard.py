"""
Regression leaderboard helpers (best-effort).

Goal:
- Provide a simple, PII-safe way to rank and compare regression runs by a metric key.
- Attach a stable retrieval_config_hash so downstream dashboards can group runs by config.
"""


import json
from collections.abc import Iterable
from typing import Any

from app.core.config import settings
from app.rag.core.query_rewrite_strategy import build_query_rewrite_strategy_spec
from app.rag.core.retrieval_config_fingerprint import build_retrieval_config_fingerprint


def _to_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _safe_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _safe_post_rerank_pipeline_summary(raw: Any) -> list[dict[str, Any]]:
    """
    Parse/normalize Evidence post-rerank pipeline into a low-cardinality summary for hashing.

    Only keeps {provider, top_n}. Avoids embedding secrets/paths into retrieval_config_hash.
    """
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        obj = json.loads(text)
    except Exception:
        return []
    if not isinstance(obj, list):
        return []

    out: list[dict[str, Any]] = []
    for item in obj:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip().lower()
        if not provider or provider in {"none", "off", "false", "0"}:
            continue
        top_n_raw = item.get("top_n")
        try:
            top_n = int(top_n_raw) if top_n_raw is not None else 0
        except Exception:
            top_n = 0
        top_n = max(0, top_n)
        out.append({"provider": provider, "top_n": top_n or None})
        if len(out) >= 4:
            break
    return out


def _build_run_retrieval_config_hash(*, rag_params: dict[str, Any]) -> str | None:
    rp = _safe_dict(rag_params)
    mode = str(rp.get("retrieval_mode") or "").strip().lower() or "hybrid"

    rewrite_enabled = bool(getattr(settings, "ENABLE_QUERY_REWRITE", False))
    rewrite_strategy_id: str | None = None
    rewrite_strategy_hash: str | None = None
    rewrite_temp: float | None = None
    rewrite_max_chars: int | None = None
    if rewrite_enabled:
        spec = build_query_rewrite_strategy_spec(getattr(settings, "QUERY_REWRITE_STRATEGY", None))
        rewrite_strategy_id = str(spec.get("strategy_id") or "").strip() or None
        rewrite_strategy_hash = str(spec.get("strategy_hash") or "").strip() or None
        try:
            rewrite_temp = float(getattr(settings, "QUERY_REWRITE_TEMPERATURE", 0.0) or 0.0)
        except Exception:
            rewrite_temp = 0.0
        try:
            rewrite_max_chars = int(getattr(settings, "QUERY_REWRITE_MAX_CHARS", 0) or 0)
        except Exception:
            rewrite_max_chars = 0

    fp = build_retrieval_config_fingerprint(
        config={
            "requested_retrieval_mode": mode,
            "retrieval_mode": mode,
            "retrieval_mode_auto_routed": False,
            "retrieval_profile": None,
            "top_k": int(rp.get("top_k") or 0) or None,
            "score_threshold": _to_float(rp.get("score_threshold")) or 0.0,
            "alpha": _to_float(rp.get("alpha")) or 0.0,
            "fusion_strategy": str(getattr(settings, "RETRIEVAL_FUSION_STRATEGY", "") or "linear"),
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
            "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "") or ""),
            "bm25_enabled": bool(getattr(settings, "BM25_INDEX_ENABLED", False)),
            "lexical_enabled": bool(getattr(settings, "LEXICAL_DB_TRGM_ENABLED", False)),
            "sparse_enabled": bool(getattr(settings, "SPARSE_RETRIEVAL_ENABLED", False)),
            "sparse_provider": str(getattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "") or ""),
            "sparse_index_persist_enabled": bool(getattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", False)),
            "colbert_enabled": bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)),
            "colbert_provider": str(getattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "") or ""),
            "colbert_index_persist_enabled": bool(getattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", False)),
            "colbert_max_docs": int(getattr(settings, "COLBERT_RETRIEVAL_MAX_DOCS", 0) or 0),
            "parent_child_auto_merge_enabled": bool(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_ENABLED", False)),
            "parent_child_auto_merge_mode": str(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_MODE", "") or ""),
            "kg_query_expansion_enabled": bool(getattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False)),
            "kg_chunk_injection_enabled": bool(getattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False)),
            "evidence_post_rerank_enabled": bool(getattr(settings, "EVIDENCE_POST_RERANK_ENABLED", False)),
            "evidence_post_rerank_provider": str(getattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "") or ""),
            "evidence_post_rerank_top_n": int(getattr(settings, "EVIDENCE_POST_RERANK_TOP_N", 0) or 0),
            "evidence_post_rerank_pipeline_enabled": bool(getattr(settings, "EVIDENCE_POST_RERANK_PIPELINE_ENABLED", False)),
            "evidence_post_rerank_pipeline": _safe_post_rerank_pipeline_summary(getattr(settings, "EVIDENCE_POST_RERANK_PIPELINE", "")),
            "query_rewrite": {
                "enabled": bool(rewrite_enabled),
                "strategy_id": rewrite_strategy_id if rewrite_enabled else None,
                "strategy_hash": rewrite_strategy_hash if rewrite_enabled else None,
                "temperature": rewrite_temp if rewrite_enabled else None,
                "max_chars": int(rewrite_max_chars or 0) if rewrite_enabled else None,
            },
        }
    )
    out = str(fp.get("hash") or "").strip()
    return out or None


def build_regression_run_leaderboard(
    *,
    runs: Iterable[object],
    metric_key: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Build a leaderboard-like list sorted by `metric_key` (descending).

    The function is intentionally tolerant of partially-populated run rows.
    """
    metric_key = str(metric_key or "").strip() or "retrieval_mrr"
    limit = max(1, min(int(limit or 0), 500))

    items: list[dict[str, Any]] = []
    for r in (runs or []):
        summary = _safe_dict(getattr(r, "summary", None))
        params = _safe_dict(getattr(r, "params", None))
        rag_params = _safe_dict(params.get("rag_params"))

        metric_value = _to_float(summary.get(metric_key))
        cfg_hash = _build_run_retrieval_config_hash(rag_params=rag_params) if rag_params else None

        items.append(
            {
                "run_id": str(getattr(r, "id", "") or ""),
                "status": str(getattr(r, "status", "") or ""),
                "created_at": getattr(r, "created_at", None),
                "finished_at": getattr(r, "finished_at", None),
                "metric_key": metric_key,
                "metric_value": metric_value,
                "retrieval_config_hash": cfg_hash,
            }
        )

    # Sort: higher is better; missing metrics go last.
    items.sort(key=lambda x: (x.get("metric_value") is None, -(x.get("metric_value") or 0.0)))
    return items[:limit]


__all__ = ["build_regression_run_leaderboard"]
