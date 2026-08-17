"""
Unified entry for KG search: recall -> expand -> rerank.
"""

import asyncio
import time
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.kg.community import build_community_reports, lazy_summarize
from app.rag.kg.search.cache import build_kg_community_summary_cache_key, kg_community_summary_cache
from app.rag.kg.search.config import RerankStrategy, ReturnType, SearchConfig
from app.rag.kg.search.expand import ExpandResult, ExpandSearcher
from app.rag.kg.search.path_verbalizer import attach_path_renderings
from app.rag.kg.search.recall import RecallSearcher
from app.rag.llm.factory import create_llm_client
from app.rag.reranker.kg import get_kg_reranker
from app.rag.reranker.types import RerankCandidate
from app.services.metrics_logger import log_metrics

logger = get_logger(__name__)


class KGSearcher:
    def __init__(self):
        self.recall_searcher = RecallSearcher()
        self.expand_searcher = ExpandSearcher()

    def _should_run_community_detection(self, *, config: SearchConfig, query_mode: str) -> tuple[bool, list[str]]:
        """
        Gate community detection so normal KG search stays fast by default.

        Returns:
            (should_run, reason_codes)
        """
        if not bool(getattr(settings, "KG_COMMUNITY_ENABLED", False)):
            return False, ["disabled"]

        if str(query_mode or "").strip().lower() != "global":
            return False, [f"skipped_mode:{query_mode}"]

        reasons = [str(x) for x in (getattr(config, "query_mode_reason_codes", []) or []) if str(x).strip()]
        require_global_pattern = bool(getattr(settings, "KG_COMMUNITY_REQUIRE_GLOBAL_PATTERN", True))
        if require_global_pattern and "global_pattern" not in set(reasons):
            return False, ["missing_global_pattern"]

        return True, ["enabled"]

    def _should_skip_expand_for_latency(
        self,
        *,
        config: SearchConfig,
        query_mode: str,
        recalled_event_count: int,
    ) -> tuple[bool, str]:
        """
        Keep fallback global searches responsive.

        Queries can resolve to "global" simply because the caller selected a dataset
        without document ids. Unless the query contains an explicit overview/global
        intent, those searches should behave like factoid KG recall and avoid a
        multi-hop expansion fan-out.
        """
        reasons = {str(x).strip() for x in (getattr(config, "query_mode_reason_codes", []) or []) if str(x).strip()}
        if (
            str(query_mode or "").strip().lower() == "local"
            and "dataset_factoid_scope" in reasons
            and int(recalled_event_count or 0) > 0
        ):
            return True, "local_factoid_precision"

        if str(query_mode or "").strip().lower() != "global":
            return False, ""
        if bool(getattr(config.expand, "enabled", True)) is False:
            return False, ""
        if config.relation_expansion_enabled is True:
            return False, ""
        if int(recalled_event_count or 0) < int(getattr(config.rerank, "max_results", 10) or 10):
            return False, ""

        confidence = str(getattr(config, "query_mode_confidence", "") or "").strip().lower()
        if confidence == "low" and "global_pattern" not in reasons and "drift_pattern" not in reasons:
            return True, "low_confidence_global_budget"
        return False, ""

    def _effective_rerank_strategy(self, *, config: SearchConfig, query_mode: str) -> RerankStrategy:
        reasons = {str(x).strip() for x in (getattr(config, "query_mode_reason_codes", []) or []) if str(x).strip()}
        if str(query_mode or "").strip().lower() == "local" and "dataset_factoid_scope" in reasons:
            return RerankStrategy.RRF
        return config.rerank.strategy

    def _lazy_community_summary_settings(self) -> dict[str, int | bool]:
        return {
            "enabled": bool(getattr(settings, "KG_LAZY_COMMUNITY_SUMMARY_ENABLED", False)),
            "top_n": max(0, int(getattr(settings, "KG_LAZY_COMMUNITY_SUMMARY_TOP_N", 3) or 3)),
            "max_tokens": max(1, int(getattr(settings, "KG_LAZY_COMMUNITY_SUMMARY_MAX_TOKENS", 300) or 300)),
            "ttl_sec": max(0, int(getattr(settings, "KG_LAZY_COMMUNITY_SUMMARY_CACHE_TTL_SEC", 86400) or 86400)),
            "max_entries": max(0, int(getattr(settings, "KG_LAZY_COMMUNITY_SUMMARY_CACHE_MAX_ENTRIES", 1024) or 1024)),
        }

    def _community_scope(
        self, *, config: SearchConfig, community_id: str, query: str, report: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "tenant_id": str(config.tenant_id) if config.tenant_id else None,
            "dataset_id": str(config.dataset_id) if config.dataset_id else None,
            "document_ids": [str(doc_id) for doc_id in (config.document_ids or [])],
            "community_id": community_id,
            "query": query,
            "report_payload": report,
        }

    def _apply_cached_community_summary(
        self,
        *,
        report: dict[str, Any],
        cache_key: str,
        ttl_sec: int,
        cache_enabled: bool,
        meta: dict[str, Any],
    ) -> bool:
        if not cache_enabled:
            return False
        cached_summary, _age_ms = kg_community_summary_cache.get(cache_key, ttl_sec=ttl_sec)
        if not cached_summary:
            return False
        report["llm_summary"] = cached_summary
        meta["cache_hits"] = int(meta["cache_hits"]) + 1
        return True

    async def _generate_lazy_summary(
        self,
        *,
        llm_client: Any,
        report: dict[str, Any],
        query: str,
        max_tokens: int,
        cache_enabled: bool,
        cache_key: str,
        ttl_sec: int,
        max_entries: int,
        meta: dict[str, Any],
    ) -> Any:
        llm_client = llm_client or await create_llm_client(scenario="kg_community_summary")
        summary = await lazy_summarize(
            community_report=report,
            query=query,
            llm_client=llm_client,
            max_tokens=max_tokens,
        )
        if summary:
            report["llm_summary"] = summary
            meta["generated"] = int(meta["generated"]) + 1
            if cache_enabled:
                kg_community_summary_cache.set(
                    cache_key,
                    summary,
                    ttl_sec=ttl_sec,
                    max_entries=max_entries,
                )
        return llm_client

    async def _apply_lazy_community_summaries(
        self,
        *,
        config: SearchConfig,
        reports: list[dict[str, Any]],
        query: str,
    ) -> dict[str, Any]:
        """
        Best-effort query-aware community summary enrichment.
        """
        summary_settings = self._lazy_community_summary_settings()
        enabled = bool(summary_settings["enabled"])
        top_n = int(summary_settings["top_n"])
        max_tokens = int(summary_settings["max_tokens"])
        ttl_sec = int(summary_settings["ttl_sec"])
        max_entries = int(summary_settings["max_entries"])

        meta: dict[str, Any] = {
            "enabled": enabled,
            "used": False,
            "cache_hits": 0,
            "generated": 0,
            "errors": 0,
        }
        if not enabled or not reports or top_n <= 0:
            return meta

        llm_client = None
        cache_enabled = ttl_sec > 0 and max_entries > 0
        for report in reports[:top_n]:
            if not isinstance(report, dict):
                continue
            community_id = str(report.get("community_id") or report.get("label") or "").strip()
            if not community_id:
                continue

            cache_key = build_kg_community_summary_cache_key(
                **self._community_scope(
                    config=config,
                    community_id=community_id,
                    query=query,
                    report=report,
                )
            )
            if self._apply_cached_community_summary(
                report=report,
                cache_key=cache_key,
                ttl_sec=ttl_sec,
                cache_enabled=cache_enabled,
                meta=meta,
            ):
                continue

            try:
                llm_client = await self._generate_lazy_summary(
                    llm_client=llm_client,
                    report=report,
                    query=query,
                    max_tokens=max_tokens,
                    cache_enabled=cache_enabled,
                    cache_key=cache_key,
                    ttl_sec=ttl_sec,
                    max_entries=max_entries,
                    meta=meta,
                )
            except Exception:
                meta["errors"] = int(meta["errors"]) + 1

        meta["used"] = bool(int(meta["cache_hits"]) > 0 or int(meta["generated"]) > 0)
        return meta

    def _rerank_stats(
        self,
        *,
        rerank_result: Any,
        event_ids_total: list[Any],
        combined_clues: list[Any],
        query_mode: str,
        rerank_strategy: RerankStrategy,
        config: SearchConfig,
        recall_result: Any,
        skip_expand: bool,
        expand_skipped_reason: str,
        recall_elapsed: float,
        expand_elapsed: float,
        rerank_elapsed: float,
        t_total: float,
        budget_meta: dict[str, Any],
    ) -> dict[str, Any]:
        stats = dict(rerank_result.stats or {})
        stats.setdefault("candidates", int(len(event_ids_total)))
        stats.setdefault("clues_returned", int(len(combined_clues)))
        stats.setdefault("query_mode", str(query_mode))
        stats.setdefault("rerank_strategy_effective", str(rerank_strategy))
        stats.setdefault(
            "query_mode_reason_codes",
            [str(x) for x in (getattr(config, "query_mode_reason_codes", []) or []) if str(x).strip()][:8],
        )
        if getattr(config, "query_mode_confidence", None) is not None:
            stats.setdefault("query_mode_confidence", str(config.query_mode_confidence or ""))
        if getattr(recall_result, "relation_debug", None):
            stats.setdefault("relation_expansion", getattr(recall_result, "relation_debug", {}) or {})
        if getattr(recall_result, "serving_layer", None):
            stats.setdefault("serving_layer", getattr(recall_result, "serving_layer", {}) or {})
        if skip_expand:
            stats.setdefault("expand_skipped", True)
            stats.setdefault("expand_skipped_reason", str(expand_skipped_reason or ""))
        stats.setdefault(
            "timing_sec",
            {
                "recall": round(float(recall_elapsed), 3),
                "expand": round(float(expand_elapsed), 3),
                "rerank": round(float(rerank_elapsed), 3),
                "total": round(float(time.perf_counter() - t_total), 3),
            },
        )
        stats.setdefault("budget", budget_meta)
        total_elapsed_ms_for_slo = float(time.perf_counter() - t_total) * 1000.0
        latency_slo_ms = max(0, int(getattr(settings, "KG_SEARCH_LATENCY_SLO_MS", 0) or 0))
        stats.setdefault(
            "slo",
            {
                "latency_slo_ms": int(latency_slo_ms),
                "elapsed_ms": round(float(total_elapsed_ms_for_slo), 1),
                "exceeded": bool(latency_slo_ms > 0 and total_elapsed_ms_for_slo > float(latency_slo_ms)),
            },
        )
        return stats

    def _event_response(
        self,
        *,
        config: SearchConfig,
        query_mode: str,
        rendered_events: list[dict[str, Any]],
        expand_result: Any,
        combined_clues: list[Any],
        stats: dict[str, Any],
        community_reports: list[dict[str, Any]],
        global_summary: str,
    ) -> dict[str, Any]:
        response = {
            "events": rendered_events,
            "entities": list(expand_result.key_final or []),
            "clues": combined_clues,
            "stats": stats,
            "community_reports": community_reports,
            "global_summary": global_summary,
        }
        if config.return_type != ReturnType.EVENT:
            return response
        response["query"] = {
            "original": config.query,
            "mode": str(query_mode),
            "mode_reason_codes": [
                str(x) for x in (getattr(config, "query_mode_reason_codes", []) or []) if str(x).strip()
            ][:8],
            "mode_confidence": (str(config.query_mode_confidence or "").strip() or None),
        }
        return response

    async def _community_summary_pass(
        self,
        *,
        config: SearchConfig,
        query_mode: str,
        expand_result: Any,
        rerank_result: Any,
        event_ids_total: list[Any],
        metrics_enabled: bool,
        doc_count: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
        community_meta: dict[str, Any] = {"enabled": False, "used": False, "reason_codes": []}
        community_reports: list[dict[str, Any]] = []
        global_summary = ""
        should_run, why = self._should_run_community_detection(config=config, query_mode=query_mode)
        community_meta["enabled"] = bool(getattr(settings, "KG_COMMUNITY_ENABLED", False))
        community_meta["reason_codes"] = list(why)
        if not should_run:
            return community_meta, community_reports, global_summary

        t_comm = time.perf_counter()
        chosen_event_ids: list[str] = []
        try:
            chosen_event_ids, community_reports, global_summary = await self._build_community_outputs(
                config=config,
                expand_result=expand_result,
                rerank_result=rerank_result,
                event_ids_total=event_ids_total,
            )
            community_meta["lazy_summary"] = await self._apply_lazy_community_summaries(
                config=config,
                reports=community_reports,
                query=str(config.query or ""),
            )
            community_meta["used"] = True
        except Exception as exc:  # noqa: BLE001
            community_meta["used"] = False
            community_meta["error"] = str(exc)[:200]
        finally:
            community_meta["elapsed_sec"] = round(float(time.perf_counter() - t_comm), 3)

        if metrics_enabled:
            self._log_community_metrics(
                config=config,
                query_mode=query_mode,
                doc_count=doc_count,
                chosen_event_ids=chosen_event_ids,
                community_reports=community_reports,
                global_summary=global_summary,
                community_meta=community_meta,
            )
        return community_meta, community_reports, global_summary

    async def _build_community_outputs(
        self,
        *,
        config: SearchConfig,
        expand_result: Any,
        rerank_result: Any,
        event_ids_total: list[Any],
    ) -> tuple[list[str], list[dict[str, Any]], str]:
        max_events = max(0, int(getattr(settings, "KG_COMMUNITY_MAX_EVENTS", 200) or 200))
        event_scores = dict(getattr(expand_result, "event_scores", {}) or {})
        scored = [(float(event_scores.get(eid, 0.0) or 0.0), str(eid)) for eid in (event_ids_total or [])]
        scored.sort(key=lambda item: (-float(item[0]), str(item[1])))
        chosen_event_ids = (
            [eid for _score, eid in scored[:max_events]] if max_events else [eid for _score, eid in scored]
        )
        ev_to_ents = self._community_event_entities(config=config, chosen_event_ids=chosen_event_ids)
        community_reports, global_summary = build_community_reports(
            entities=list(expand_result.key_final or []),
            events=list(rerank_result.items or []),
            event_entities=ev_to_ents,
            max_entities_per_event=int(getattr(settings, "KG_COMMUNITY_MAX_ENTITIES_PER_EVENT", 12) or 12),
            min_edge_weight=float(getattr(settings, "KG_COMMUNITY_MIN_EDGE_WEIGHT", 2.0) or 2.0),
            label_propagation_iters=int(getattr(settings, "KG_COMMUNITY_LABEL_PROPAGATION_ITERS", 25) or 25),
            max_communities=int(getattr(settings, "KG_COMMUNITY_MAX_COMMUNITIES", 12) or 12),
            max_entities_per_community=int(getattr(settings, "KG_COMMUNITY_MAX_ENTITIES_PER_COMMUNITY", 12) or 12),
            max_events_per_community=int(getattr(settings, "KG_COMMUNITY_MAX_EVENTS_PER_COMMUNITY", 6) or 6),
            global_summary_max_chars=int(getattr(settings, "KG_COMMUNITY_GLOBAL_SUMMARY_MAX_CHARS", 3200) or 3200),
        )
        return chosen_event_ids, community_reports, global_summary

    def _community_event_entities(self, *, config: SearchConfig, chosen_event_ids: list[str]) -> dict[str, list[str]]:
        ev_to_ents: dict[str, list[str]] = {}
        if not chosen_event_ids:
            return ev_to_ents
        from app.rag.kg.repository import EventRepository, get_session  # noqa: WPS433

        session = get_session()
        try:
            repo = EventRepository(session)
            assoc = repo.get_event_entities(chosen_event_ids, tenant_id=config.tenant_id)
            for ev_id, links in (assoc or {}).items():
                ent_ids = [str(getattr(link, "entity_id", "") or "").strip() for link in (links or [])]
                ent_ids = [entity_id for entity_id in ent_ids if entity_id]
                if ent_ids:
                    ev_to_ents[str(ev_id)] = ent_ids
        finally:
            session.close()
        return ev_to_ents

    def _log_community_metrics(
        self,
        *,
        config: SearchConfig,
        query_mode: str,
        doc_count: int,
        chosen_event_ids: list[str],
        community_reports: list[dict[str, Any]],
        global_summary: str,
        community_meta: dict[str, Any],
    ) -> None:
        try:
            log_metrics(
                {
                    "event": "kg.search.community",
                    "tenant_id": str(config.tenant_id) if config.tenant_id else None,
                    "doc_count": int(doc_count),
                    "query_mode": str(query_mode),
                    "events_considered": int(len(chosen_event_ids)),
                    "reports": int(len(community_reports or [])),
                    "global_summary_chars": int(len(global_summary or "")),
                    "elapsed_sec": float(community_meta.get("elapsed_sec") or 0.0),
                }
            )
        except Exception as exc:
            logger.debug("Ignoring KG community metrics log failure: %s", exc)

    async def search(self, config: SearchConfig) -> dict[str, Any]:
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

    async def _search_impl(self, config: SearchConfig) -> dict[str, Any]:
        metrics_enabled = bool(getattr(settings, "KG_SEARCH_METRICS_ENABLED", False))
        doc_count = len(config.document_ids or [])
        query_chars = len(config.query or "")
        query_mode = str(getattr(config, "query_mode", "") or "").strip().lower() or "global"
        t_total = time.perf_counter()

        # recall
        t0 = time.perf_counter()
        recall_result = await self.recall_searcher.search(config)
        recall_elapsed = time.perf_counter() - t0
        expand_budget_sec = max(0.0, float(getattr(settings, "KG_SEARCH_EXPAND_BUDGET_SEC", 0.0) or 0.0))
        budget_meta: dict[str, Any] = {
            "expand_budget_sec": float(expand_budget_sec),
            "recall_elapsed_sec": round(float(recall_elapsed), 3),
            "expand_budget_exhausted": bool(expand_budget_sec > 0.0 and float(recall_elapsed) >= expand_budget_sec),
        }
        if metrics_enabled:
            rel_dbg = getattr(recall_result, "relation_debug", None) or {}
            serving_dbg = getattr(recall_result, "serving_layer", None) or {}
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
                    "serving_layer_enabled": bool(serving_dbg.get("enabled", False)),
                    "serving_layer_kept": int(serving_dbg.get("kept", 0) or 0),
                    "serving_layer_dropped": int(serving_dbg.get("dropped", 0) or 0),
                    "elapsed_sec": round(float(recall_elapsed), 3),
                }
            )

        # expand
        t0 = time.perf_counter()
        skip_expand, expand_skipped_reason = self._should_skip_expand_for_latency(
            config=config,
            query_mode=query_mode,
            recalled_event_count=len(recall_result.event_ids or []),
        )
        if bool(budget_meta.get("expand_budget_exhausted")) and bool(getattr(config.expand, "enabled", True)):
            skip_expand = True
            expand_skipped_reason = "recall_budget_exhausted"
        if skip_expand:
            expand_result = ExpandResult(
                key_final=list(recall_result.key_final or []),
                event_ids=list(recall_result.event_ids or []),
                clues=list(recall_result.clues or []),
                event_scores=dict(recall_result.event_scores or {}),
                event_hops=dict(getattr(recall_result, "event_hops", {}) or {}),
            )
        else:
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
                    "skipped": bool(skip_expand),
                    "skipped_reason": str(expand_skipped_reason or ""),
                    "elapsed_sec": round(float(expand_elapsed), 3),
                }
            )

        # rerank
        t0 = time.perf_counter()
        event_ids_total = list(expand_result.event_ids or [])
        candidates = [RerankCandidate(id=str(eid), text="") for eid in event_ids_total]
        rerank_strategy = self._effective_rerank_strategy(config=config, query_mode=query_mode)
        reranker = get_kg_reranker(rerank_strategy)
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
        stats = self._rerank_stats(
            rerank_result=rerank_result,
            event_ids_total=event_ids_total,
            combined_clues=combined_clues,
            query_mode=query_mode,
            rerank_strategy=rerank_strategy,
            config=config,
            recall_result=recall_result,
            skip_expand=skip_expand,
            expand_skipped_reason=expand_skipped_reason,
            recall_elapsed=recall_elapsed,
            expand_elapsed=expand_elapsed,
            rerank_elapsed=rerank_elapsed,
            t_total=t_total,
            budget_meta=budget_meta,
        )
        latency_slo_ms = int(stats.get("slo", {}).get("latency_slo_ms", 0) or 0)

        if metrics_enabled:
            total_elapsed = time.perf_counter() - t_total
            log_metrics(
                {
                    "event": "kg.search.rerank",
                    "tenant_id": str(config.tenant_id) if config.tenant_id else None,
                    "doc_count": int(doc_count),
                    "query_mode": str(query_mode),
                    "strategy": str(rerank_strategy),
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
                    "strategy": str(rerank_strategy),
                    "returned": int(len(rerank_result.items or [])),
                    "elapsed_sec": round(float(total_elapsed), 3),
                    "latency_slo_ms": int(latency_slo_ms),
                    "slo_exceeded": bool(latency_slo_ms > 0 and (total_elapsed * 1000.0) > float(latency_slo_ms)),
                    "expand_budget_exhausted": bool(budget_meta.get("expand_budget_exhausted")),
                }
            )

        community_meta, community_reports, global_summary = await self._community_summary_pass(
            config=config,
            query_mode=query_mode,
            expand_result=expand_result,
            rerank_result=rerank_result,
            event_ids_total=event_ids_total,
            metrics_enabled=metrics_enabled,
            doc_count=doc_count,
        )

        stats.setdefault("community", community_meta)
        rendered_events = attach_path_renderings(
            events=list(rerank_result.items or []),
            key_entities=list(expand_result.key_final or []),
            query=str(config.query or ""),
            community_reports=community_reports,
        )
        return self._event_response(
            config=config,
            query_mode=query_mode,
            rendered_events=rendered_events,
            expand_result=expand_result,
            combined_clues=combined_clues,
            stats=stats,
            community_reports=community_reports,
            global_summary=global_summary,
        )
