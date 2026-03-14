"""
Unified entry for KG search: recall -> expand -> rerank.
"""
import asyncio
import time
from typing import Any, Dict

from app.core.config import settings
from app.rag.kg.search.config import ReturnType, SearchConfig
from app.rag.kg.search.expand import ExpandSearcher
from app.rag.kg.search.recall import RecallSearcher
from app.rag.reranker.kg import get_kg_reranker
from app.rag.reranker.types import RerankCandidate
from app.services.metrics_logger import log_metrics


class KGSearcher:
    def __init__(self):
        self.recall_searcher = RecallSearcher()
        self.expand_searcher = ExpandSearcher()

    async def search(self, config: SearchConfig) -> Dict[str, Any]:
        timeout_sec = float(getattr(settings, "KG_SEARCH_TIMEOUT_SEC", 0.0) or 0.0)
        if timeout_sec <= 0:
            return await self._search_impl(config)

        t0 = time.perf_counter()
        try:
            return await asyncio.wait_for(self._search_impl(config), timeout=timeout_sec)
        except asyncio.TimeoutError:
            if bool(getattr(settings, "KG_SEARCH_METRICS_ENABLED", False)):
                log_metrics(
                    {
                        "event": "kg.search.timeout",
                        "tenant_id": str(config.tenant_id) if config.tenant_id else None,
                        "doc_count": int(len(config.document_ids or [])),
                        "query_chars": int(len(config.query or "")),
                        "timeout_sec": float(timeout_sec),
                        "elapsed_sec": round(float(time.perf_counter() - t0), 3),
                    }
                )
            raise

    async def _search_impl(self, config: SearchConfig) -> Dict[str, Any]:
        metrics_enabled = bool(getattr(settings, "KG_SEARCH_METRICS_ENABLED", False))
        doc_count = len(config.document_ids or [])
        query_chars = len(config.query or "")
        query_mode = str(getattr(config, "query_mode", "") or "").strip().lower() or "global"
        t_total = time.perf_counter()

        # recall
        t0 = time.perf_counter()
        recall_result = await self.recall_searcher.search(config)
        recall_elapsed = time.perf_counter() - t0
        if metrics_enabled:
            rel_dbg = getattr(recall_result, "relation_debug", None) or {}
            log_metrics(
                {
                    "event": "kg.search.recall",
                    "tenant_id": str(config.tenant_id) if config.tenant_id else None,
                    "doc_count": int(doc_count),
                    "query_chars": int(query_chars),
                    "query_mode": str(query_mode),
                    "key_final": int(len(recall_result.key_final or [])),
                    "event_ids": int(len(recall_result.event_ids or [])),
                    "clues": int(len(recall_result.clues or [])),
                    "relation_enabled": bool(rel_dbg.get("enabled")),
                    "relation_edges_fetched": int(rel_dbg.get("edges_fetched", 0) or 0),
                    "relation_edges_used": int(rel_dbg.get("edges_used", 0) or 0),
                    "relation_neighbors_selected": int(rel_dbg.get("neighbors_selected", 0) or 0),
                    "elapsed_sec": round(float(recall_elapsed), 3),
                }
            )

        # expand (currently passthrough)
        t0 = time.perf_counter()
        expand_result = await self.expand_searcher.expand(config, recall_result)
        expand_elapsed = time.perf_counter() - t0
        if metrics_enabled:
            log_metrics(
                {
                    "event": "kg.search.expand",
                    "tenant_id": str(config.tenant_id) if config.tenant_id else None,
                    "doc_count": int(doc_count),
                    "query_mode": str(query_mode),
                    "expand_enabled": bool(getattr(config.expand, "enabled", True)),
                    "max_hops": int(getattr(config.expand, "max_hops", 0) or 0),
                    "entities_per_hop": int(getattr(config.expand, "entities_per_hop", 0) or 0),
                    "max_events_per_hop": int(getattr(config.expand, "max_events_per_hop", 0) or 0),
                    "key_final": int(len(expand_result.key_final or [])),
                    "event_ids": int(len(expand_result.event_ids or [])),
                    "clues": int(len(expand_result.clues or [])),
                    "elapsed_sec": round(float(expand_elapsed), 3),
                }
            )

        # rerank
        t0 = time.perf_counter()
        event_ids_total = list(expand_result.event_ids or [])
        candidates = [RerankCandidate(id=str(eid), text="") for eid in event_ids_total]
        reranker = get_kg_reranker(config.rerank.strategy)
        rerank_result = await reranker.arerank_kg(
            query=config.query,
            candidates=candidates,
            config=config,
            event_scores=expand_result.event_scores,
            key_final=expand_result.key_final,
            query_vector=getattr(recall_result, "query_vector", None),
            event_hops=getattr(expand_result, "event_hops", None),
        )
        rerank_elapsed = time.perf_counter() - t0

        combined_clues = list((expand_result.clues or [])) + list((rerank_result.clues or []))
        stats = dict(rerank_result.stats or {})
        stats.setdefault("candidates", int(len(event_ids_total)))
        stats.setdefault("clues_returned", int(len(combined_clues)))
        stats.setdefault("query_mode", str(query_mode))
        stats.setdefault(
            "query_mode_reason_codes",
            [str(x) for x in (getattr(config, "query_mode_reason_codes", []) or []) if str(x).strip()][:8],
        )
        if getattr(config, "query_mode_confidence", None) is not None:
            stats.setdefault("query_mode_confidence", str(getattr(config, "query_mode_confidence") or ""))
        if getattr(recall_result, "relation_debug", None):
            stats.setdefault("relation_expansion", getattr(recall_result, "relation_debug", {}) or {})
        stats.setdefault(
            "timing_sec",
            {
                "recall": round(float(recall_elapsed), 3),
                "expand": round(float(expand_elapsed), 3),
                "rerank": round(float(rerank_elapsed), 3),
                "total": round(float(time.perf_counter() - t_total), 3),
            },
        )

        if metrics_enabled:
            total_elapsed = time.perf_counter() - t_total
            log_metrics(
                {
                    "event": "kg.search.rerank",
                    "tenant_id": str(config.tenant_id) if config.tenant_id else None,
                    "doc_count": int(doc_count),
                    "query_mode": str(query_mode),
                    "strategy": str(config.rerank.strategy),
                    "candidates_total": int(len(event_ids_total)),
                    "returned": int(len(rerank_result.items or [])),
                    "clues": int(len(combined_clues)),
                    "elapsed_sec": round(float(rerank_elapsed), 3),
                }
            )
            log_metrics(
                {
                    "event": "kg.search.total",
                    "tenant_id": str(config.tenant_id) if config.tenant_id else None,
                    "doc_count": int(doc_count),
                    "query_chars": int(query_chars),
                    "query_mode": str(query_mode),
                    "strategy": str(config.rerank.strategy),
                    "returned": int(len(rerank_result.items or [])),
                    "elapsed_sec": round(float(total_elapsed), 3),
                }
            )

        if config.return_type == ReturnType.EVENT:
            return {
                "events": rerank_result.items,
                "entities": list(expand_result.key_final or []),
                "clues": combined_clues,
                "stats": stats,
                "query": {
                    "original": config.query,
                    "mode": str(query_mode),
                    "mode_reason_codes": [
                        str(x) for x in (getattr(config, "query_mode_reason_codes", []) or []) if str(x).strip()
                    ][:8],
                    "mode_confidence": (str(getattr(config, "query_mode_confidence") or "").strip() or None),
                },
            }

        return {
            "events": rerank_result.items,
            "entities": list(expand_result.key_final or []),
            "clues": combined_clues,
            "stats": stats,
        }
