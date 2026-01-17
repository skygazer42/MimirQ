"""
Unified entry for KG search: recall -> expand -> rerank.
"""
import time
from typing import Any, Dict

from app.core.config import settings
from app.rag.kg.search.config import SearchConfig, ReturnType
from app.rag.kg.search.recall import RecallSearcher
from app.rag.kg.search.expand import ExpandSearcher
from app.rag.reranker.kg import get_kg_reranker
from app.rag.reranker.types import RerankCandidate
from app.rag.kg.utils import get_logger
from app.services.metrics_logger import log_metrics

logger = get_logger("kg.search.searcher")


def _cap_clues(clues: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    max_clues = max(0, int(getattr(settings, "KG_SEARCH_MAX_CLUES", 0) or 0))
    if max_clues <= 0:
        return clues, 0
    if len(clues) <= max_clues:
        return clues, 0
    return clues[:max_clues], len(clues) - max_clues


class KGSearcher:
    def __init__(self):
        self.recall_searcher = RecallSearcher()
        self.expand_searcher = ExpandSearcher()

    async def search(self, config: SearchConfig) -> Dict[str, Any]:
        metrics_enabled = bool(getattr(settings, "KG_SEARCH_METRICS_ENABLED", False))
        doc_count = len(config.document_ids or [])
        query_chars = len(config.query or "")
        t_total = time.perf_counter()

        # recall
        t0 = time.perf_counter()
        recall_result = await self.recall_searcher.search(config)
        recall_elapsed = time.perf_counter() - t0
        if metrics_enabled:
            log_metrics(
                {
                    "event": "kg.search.recall",
                    "tenant_id": str(config.tenant_id) if config.tenant_id else None,
                    "doc_count": int(doc_count),
                    "query_chars": int(query_chars),
                    "key_final": int(len(recall_result.key_final or [])),
                    "event_ids": int(len(recall_result.event_ids or [])),
                    "clues": int(len(recall_result.clues or [])),
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
        candidates = [RerankCandidate(id=str(eid), text="") for eid in expand_result.event_ids]
        reranker = get_kg_reranker(config.rerank.strategy)
        rerank_result = await reranker.arerank_kg(
            query=config.query,
            candidates=candidates,
            config=config,
            event_scores=expand_result.event_scores,
            key_final=expand_result.key_final,
        )
        rerank_elapsed = time.perf_counter() - t0

        combined_clues = list((expand_result.clues or [])) + list((rerank_result.clues or []))
        combined_clues, clues_dropped = _cap_clues(combined_clues)
        stats = dict(rerank_result.stats or {})
        stats.setdefault("clues_returned", len(combined_clues))
        if clues_dropped:
            stats["clues_dropped"] = int(stats.get("clues_dropped", 0) or 0) + int(clues_dropped)
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
                    "strategy": str(config.rerank.strategy),
                    "candidates": int(len(expand_result.event_ids or [])),
                    "returned": int(len(rerank_result.items or [])),
                    "clues": int(len(combined_clues)),
                    "clues_dropped": int(clues_dropped),
                    "elapsed_sec": round(float(rerank_elapsed), 3),
                }
            )
            log_metrics(
                {
                    "event": "kg.search.total",
                    "tenant_id": str(config.tenant_id) if config.tenant_id else None,
                    "doc_count": int(doc_count),
                    "query_chars": int(query_chars),
                    "strategy": str(config.rerank.strategy),
                    "returned": int(len(rerank_result.items or [])),
                    "elapsed_sec": round(float(total_elapsed), 3),
                }
            )

        if config.return_type == ReturnType.EVENT:
            return {
                "events": rerank_result.items,
                "clues": combined_clues,
                "stats": stats,
                "query": {"original": config.query},
            }

        return {
            "events": rerank_result.items,
            "clues": combined_clues,
            "stats": stats,
        }
