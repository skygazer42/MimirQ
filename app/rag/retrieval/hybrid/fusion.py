"""Channel fusion and lightweight reranking for the hybrid retriever.

Split out of ``app.rag.retriever`` (see ``app.rag.retrieval.hybrid``). The
methods below run on the ``HybridRetriever`` instance via mixin inheritance.
"""

import math
from collections import Counter
from typing import Any

from app.core.config import settings
from app.rag.core.hashing import stable_hash
from app.rag.retrieval.hybrid.common import (
    NON_CRITICAL_RETRIEVER_FALLBACK_LOG,
    _apply_exact_content_bonus_to_result,
    _float_or_default,
    logger,
)
from app.rag.retrieval.query_phrase_match import query_phrase_match


class FusionMixin:
    """Merges per-channel candidate lists and applies weight/MMR reranking."""

    _FUSION_CHANNELS = ("vector", "bm25", "lexical", "sparse")

    @staticmethod
    def _resolve_query_chunk_type_signal(text: str | None) -> str | None:
        raw = str(text or "").strip().lower()
        if not raw:
            return None
        if any(token in raw for token in ("表格", "字段", "列", "schema", "table", "column")):
            return "table"
        if any(token in raw for token in ("公式", "latex", "equation", "math", "公式识别")):
            return "formula"
        if any(token in raw for token in ("代码", "sql", "python", "bash", "json", "yaml", "脚本", "code")):
            return "code"
        if any(token in raw for token in ("图表", "曲线", "趋势图", "chart", "plot", "graph")):
            return "chart_data"
        if any(token in raw for token in ("公章", "印章", "seal", "stamp")):
            return "seal"
        return None

    @staticmethod
    def _build_fusion_runtime(query: str | None) -> dict[str, Any]:
        field_aware_enabled = bool(getattr(settings, "RETRIEVAL_FIELD_AWARE_RECALL_ENABLED", False))
        field_aware_title_boost = max(0.0, float(getattr(settings, "RETRIEVAL_FIELD_AWARE_TITLE_BOOST", 0.08) or 0.0))
        field_aware_heading_boost = max(
            0.0,
            float(getattr(settings, "RETRIEVAL_FIELD_AWARE_HEADING_BOOST", 0.05) or 0.0),
        )
        field_aware_max_boost = max(0.0, float(getattr(settings, "RETRIEVAL_FIELD_AWARE_MAX_BOOST", 0.10) or 0.0))
        chunk_type_weighting_enabled = bool(getattr(settings, "RETRIEVAL_CHUNK_TYPE_WEIGHTING_ENABLED", False))
        chunk_type_match_boost = max(0.0, float(getattr(settings, "RETRIEVAL_CHUNK_TYPE_MATCH_BOOST", 0.08) or 0.0))
        return {
            "field_aware_enabled": field_aware_enabled,
            "field_aware_title_boost": min(field_aware_title_boost, field_aware_max_boost),
            "field_aware_heading_boost": min(field_aware_heading_boost, field_aware_max_boost),
            "field_aware_max_boost": field_aware_max_boost,
            "chunk_type_weighting_enabled": chunk_type_weighting_enabled,
            "chunk_type_match_boost": chunk_type_match_boost,
            "preferred_chunk_type": FusionMixin._resolve_query_chunk_type_signal(query),
        }

    @staticmethod
    def _resolve_chunk_type(result: dict[str, Any]) -> str:
        meta = result.get("metadata") or {}
        raw = str(meta.get("chunk_type") or meta.get("content_type") or meta.get("visual_kind") or "").strip().lower()
        if raw in {"text", "formula", "table", "code", "figure", "chart_data", "seal"}:
            return raw
        if raw == "chart":
            return "figure"
        role = str(meta.get("chunk_semantic_role") or "").strip().lower()
        if role == "code":
            return "code"
        if role == "table":
            return "table"
        return "text"

    @staticmethod
    def _chunk_type_boost(chunk_type: str, runtime: dict[str, Any]) -> float:
        if not runtime["chunk_type_weighting_enabled"] or not runtime["preferred_chunk_type"]:
            return 0.0
        if chunk_type == runtime["preferred_chunk_type"]:
            return float(runtime["chunk_type_match_boost"])
        if runtime["preferred_chunk_type"] == "chart_data" and chunk_type == "figure":
            return max(0.0, float(runtime["chunk_type_match_boost"]) * 0.75)
        return 0.0

    def _resolve_field_signal(self, result: dict[str, Any]) -> str:
        meta = result.get("metadata") or {}
        hinted = (
            str(meta.get("embedding_field_role") or meta.get("embedding_field_kind") or meta.get("field_channel") or "")
            .strip()
            .lower()
        )
        if hinted in {"title", "heading", "body"}:
            return hinted
        chunk_id = str(result.get("chunk_id") or meta.get("chunk_id") or "").strip().lower()
        if chunk_id.endswith(":title"):
            return "title"
        if chunk_id.endswith(":heading"):
            return "heading"
        return "body"

    @staticmethod
    def _field_boost(field_signal: str, runtime: dict[str, Any]) -> float:
        if not runtime["field_aware_enabled"]:
            return 0.0
        if field_signal == "title":
            return float(runtime["field_aware_title_boost"])
        if field_signal == "heading":
            return float(runtime["field_aware_heading_boost"])
        return 0.0

    def _normalize_channel_results(
        self,
        results: list[dict[str, Any]],
        *,
        channel: str,
        runtime: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        if not results:
            return {}
        scores = [result.get("score", 0.0) for result in results]
        min_score = min(scores)
        max_score = max(scores)
        score_range = max_score - min_score if max_score > min_score else 1.0
        normalized: dict[str, dict[str, Any]] = {}
        for result in results:
            key = self._result_key(result)
            norm_score = (result.get("score", 0.0) - min_score) / score_range
            chunk_type = self._resolve_chunk_type(result)
            chunk_type_boost = self._chunk_type_boost(chunk_type, runtime)
            field_signal = "body"
            field_boost = 0.0
            if channel == "vector":
                field_signal = self._resolve_field_signal(result)
                field_boost = min(self._field_boost(field_signal, runtime), runtime["field_aware_max_boost"])
            scored = float(norm_score) + float(field_boost) + float(chunk_type_boost)
            existing = normalized.get(key)
            if existing is not None and float(scored) <= float(existing.get("score", 0.0) or 0.0):
                continue
            normalized[key] = {
                "score": float(scored),
                "base_score": float(norm_score),
                "data": result,
                "chunk_type": chunk_type,
                "chunk_type_boost": float(chunk_type_boost),
                "field_aware_signal": field_signal if channel == "vector" else None,
                "field_aware_boost": float(field_boost if channel == "vector" else 0.0),
            }
        return normalized

    def _update_fusion_observability(
        self,
        *,
        vector_norm: dict[str, dict[str, Any]],
        runtime: dict[str, Any],
    ) -> None:
        try:
            if not isinstance(self._last_channel_metrics, dict):
                return
            field_signal_counts: Counter[str] = Counter()
            boosted = 0
            chunk_type_counts: Counter[str] = Counter()
            chunk_boosted = 0
            for payload in vector_norm.values():
                signal = str(payload.get("field_aware_signal") or "body").strip().lower() or "body"
                field_signal_counts[signal] += 1
                if float(payload.get("field_aware_boost") or 0.0) > 0.0:
                    boosted += 1
                chunk_signal = str(payload.get("chunk_type") or "text").strip().lower() or "text"
                chunk_type_counts[chunk_signal] += 1
                if float(payload.get("chunk_type_boost") or 0.0) > 0.0:
                    chunk_boosted += 1
            self._last_channel_metrics["field_aware"] = {
                "enabled": bool(runtime["field_aware_enabled"]),
                "title_boost": round(float(runtime["field_aware_title_boost"]), 6),
                "heading_boost": round(float(runtime["field_aware_heading_boost"]), 6),
                "max_boost": round(float(runtime["field_aware_max_boost"]), 6),
                "candidates": int(len(vector_norm)),
                "boosted_candidates": int(boosted),
                "signals": dict(sorted((str(key), int(value)) for key, value in field_signal_counts.items())),
            }
            self._last_channel_metrics["chunk_type_weighting"] = {
                "enabled": bool(runtime["chunk_type_weighting_enabled"]),
                "preferred_chunk_type": runtime["preferred_chunk_type"],
                "match_boost": round(float(runtime["chunk_type_match_boost"]), 6),
                "candidates": int(len(vector_norm)),
                "boosted_candidates": int(chunk_boosted),
                "signals": dict(sorted((str(key), int(value)) for key, value in chunk_type_counts.items())),
            }
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _attach_field_aware_signal(
        self,
        item: dict[str, Any],
        *,
        key: str,
        channel_norms: dict[str, dict[str, dict[str, Any]]],
    ) -> None:
        vector_payload = channel_norms["vector"].get(key, {})
        field_signal = vector_payload.get("field_aware_signal")
        field_boost = float(vector_payload.get("field_aware_boost") or 0.0)
        chunk_type = None
        chunk_type_boost = 0.0
        for channel in self._FUSION_CHANNELS:
            payload = channel_norms[channel].get(key, {})
            chunk_type = chunk_type or payload.get("chunk_type")
            chunk_type_boost = max(chunk_type_boost, float(payload.get("chunk_type_boost") or 0.0))
        if field_signal:
            item["field_aware_signal"] = str(field_signal)
        if field_boost > 0.0:
            item["field_aware_boost"] = field_boost
        if chunk_type:
            item["chunk_type_signal"] = str(chunk_type)
        if chunk_type_boost > 0.0:
            item["chunk_type_boost"] = chunk_type_boost

    @staticmethod
    def _channel_score(
        channel_norms: dict[str, dict[str, dict[str, Any]]],
        channel: str,
        key: str,
    ) -> float:
        return float(channel_norms[channel].get(key, {}).get("score", 0.0) or 0.0)

    @staticmethod
    def _all_channel_keys(channel_norms: dict[str, dict[str, dict[str, Any]]]) -> list[str]:
        return sorted({key for payload in channel_norms.values() for key in payload.keys()})

    def _merged_channel_data(
        self,
        *,
        key: str,
        channel_norms: dict[str, dict[str, dict[str, Any]]],
    ) -> dict[str, Any] | None:
        channel_payloads = [channel_norms[channel].get(key, {}) for channel in self._FUSION_CHANNELS]
        data = next((payload.get("data") for payload in channel_payloads if payload.get("data")), None)
        if not data:
            return None
        merged_meta = dict(data.get("metadata") or {})
        for payload in channel_payloads:
            source = payload.get("data")
            if not source or source is data:
                continue
            source_meta = source.get("metadata") or {}
            for meta_key, meta_value in source_meta.items():
                if meta_key not in merged_meta or merged_meta.get(meta_key) in (None, "", [], {}):
                    merged_meta[meta_key] = meta_value
        merged_data = dict(data)
        merged_data["metadata"] = merged_meta
        if merged_data.get("chunk_id"):
            return merged_data
        for payload in channel_payloads:
            source = payload.get("data")
            if source and source.get("chunk_id"):
                merged_data["chunk_id"] = source.get("chunk_id")
                break
        return merged_data

    def _rank_sort_key(self, result: dict[str, Any]) -> tuple[float, str]:
        return (-float(result.get("score", 0.0) or 0.0), self._result_key(result))

    def _build_rank_map(self, results: list[dict[str, Any]]) -> dict[str, int]:
        rank_map: dict[str, int] = {}
        for index, result in enumerate(results, 1):
            key = self._result_key(result)
            if key not in rank_map:
                rank_map[key] = index
        return rank_map

    @staticmethod
    def _rrf_raw_score(*, rank_maps: dict[str, dict[str, int]], key: str, k0: int) -> float:
        total = 0.0
        for channel in FusionMixin._FUSION_CHANNELS:
            rank = rank_maps[channel].get(key)
            total += (1.0 / (k0 + rank)) if rank else 0.0
        return total

    @staticmethod
    def _rank_score(rank_map: dict[str, int], key: str) -> float:
        rank = rank_map.get(key)
        if not rank or int(rank) <= 0:
            return 0.0
        return 1.0 / float(rank)

    def _build_rrf_merged_items(
        self,
        *,
        channel_norms: dict[str, dict[str, dict[str, Any]]],
        rank_maps: dict[str, dict[str, int]],
        k0: int,
        strategy: str,
        include_rank_scores: bool,
    ) -> tuple[dict[str, dict[str, Any]], list[float], list[str]]:
        merged: dict[str, dict[str, Any]] = {}
        raw_scores: list[float] = []
        keys = self._all_channel_keys(channel_norms)
        for key in keys:
            data = self._merged_channel_data(key=key, channel_norms=channel_norms)
            if not data:
                continue
            rrf_raw = self._rrf_raw_score(rank_maps=rank_maps, key=key, k0=k0)
            raw_scores.append(float(rrf_raw))
            item = {
                **data,
                "vector_score": self._channel_score(channel_norms, "vector", key),
                "bm25_score": self._channel_score(channel_norms, "bm25", key),
                "lexical_score": self._channel_score(channel_norms, "lexical", key),
                "sparse_score": self._channel_score(channel_norms, "sparse", key),
                "rrf_score_raw": float(rrf_raw),
                "rrf_k": int(k0),
                "rrf_rank_vector": rank_maps["vector"].get(key),
                "rrf_rank_bm25": rank_maps["bm25"].get(key),
                "rrf_rank_lexical": rank_maps["lexical"].get(key),
                "rrf_rank_sparse": rank_maps["sparse"].get(key),
                "fusion_strategy": strategy,
                "score": float(rrf_raw),
            }
            if include_rank_scores:
                item.update(
                    {
                        "vector_rank_score": self._rank_score(rank_maps["vector"], key),
                        "bm25_rank_score": self._rank_score(rank_maps["bm25"], key),
                        "lexical_rank_score": self._rank_score(rank_maps["lexical"], key),
                        "sparse_rank_score": self._rank_score(rank_maps["sparse"], key),
                    }
                )
            self._attach_field_aware_signal(item, key=key, channel_norms=channel_norms)
            merged[key] = item
        return merged, raw_scores, keys

    @staticmethod
    def _normalize_raw_scores(merged: dict[str, dict[str, Any]], raw_scores: list[float]) -> None:
        if not merged:
            return
        min_score = min(raw_scores) if raw_scores else 0.0
        max_score = max(raw_scores) if raw_scores else 0.0
        score_range = max_score - min_score if max_score > min_score else 1.0
        for item in merged.values():
            raw = float(item.get("rrf_score_raw", 0.0) or 0.0)
            item["score"] = (raw - min_score) / score_range

    def _apply_phrase_bonus(self, *, query: str | None, merged: dict[str, dict[str, Any]]) -> None:
        if not query:
            return
        phrase_boost_weight = max(
            0.0,
            float(getattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35) or 0.0),
        )
        for item in merged.values():
            _apply_exact_content_bonus_to_result(
                query=query,
                result=item,
                phrase_boost_weight=phrase_boost_weight,
            )

    def _sort_key_rrf(self, item: dict[str, Any]) -> tuple[float, float, float, float, float, float, str]:
        return (
            -float(item.get("score", 0.0) or 0.0),
            -float(item.get("rrf_score_raw", 0.0) or 0.0),
            -float(item.get("vector_score", 0.0) or 0.0),
            -float(item.get("bm25_score", 0.0) or 0.0),
            -float(item.get("lexical_score", 0.0) or 0.0),
            -float(item.get("sparse_score", 0.0) or 0.0),
            self._result_key(item),
        )

    def _sort_key_budgeted_rrf(self, item: dict[str, Any]) -> tuple[float, float, float, float, float, float, str]:
        return (
            -float(item.get("score", 0.0) or 0.0),
            -float(item.get("rrf_score_raw", 0.0) or 0.0),
            -float(item.get("vector_rank_score", 0.0) or 0.0),
            -float(item.get("bm25_rank_score", 0.0) or 0.0),
            -float(item.get("lexical_rank_score", 0.0) or 0.0),
            -float(item.get("sparse_rank_score", 0.0) or 0.0),
            self._result_key(item),
        )

    @staticmethod
    def _coerce_budgets(raw: Any) -> dict[str, int]:
        if not isinstance(raw, dict):
            return {}
        budgets: dict[str, int] = {}
        for key, value in raw.items():
            channel = str(key or "").strip().lower()
            if not channel:
                continue
            try:
                budgets[channel] = max(0, int(value) if value is not None else 0)
            except (TypeError, ValueError, AttributeError):
                continue
        return budgets

    @staticmethod
    def _coerce_min_scores(raw: Any) -> dict[str, float]:
        if not isinstance(raw, dict):
            return {}
        min_scores: dict[str, float] = {}
        for key, value in raw.items():
            channel = str(key or "").strip().lower()
            if not channel:
                continue
            try:
                min_scores[channel] = max(0.0, min(1.0, float(value) if value is not None else 0.0))
            except (TypeError, ValueError, AttributeError):
                continue
        return min_scores

    @staticmethod
    def _coerce_weights(raw: Any) -> dict[str, float]:
        if not isinstance(raw, dict):
            return {}
        allowed = set(FusionMixin._FUSION_CHANNELS)
        weights: dict[str, float] = {}
        for key, value in raw.items():
            channel = str(key or "").strip().lower()
            if not channel or channel not in allowed:
                continue
            try:
                weight = float(value)
            except (TypeError, ValueError, AttributeError):
                continue
            if weight > 0.0:
                weights[channel] = weight
        return weights

    @classmethod
    def _resolve_budgeted_budgets(
        cls,
        *,
        configured: dict[str, int],
        channel_results: dict[str, list[dict[str, Any]]],
        k_prefix: int,
    ) -> dict[str, int]:
        if configured:
            return configured
        budgets = {channel: 0 for channel in cls._FUSION_CHANNELS}
        active_channels = [channel for channel in cls._FUSION_CHANNELS if channel_results[channel]]
        remaining = int(k_prefix)
        for channel in active_channels:
            if remaining <= 0:
                break
            budgets[channel] = 1
            remaining -= 1
        index = 0
        while remaining > 0 and active_channels:
            channel = active_channels[index % len(active_channels)]
            budgets[channel] = int(budgets.get(channel, 0) or 0) + 1
            remaining -= 1
            index += 1
        return budgets

    def _candidate_eligible(
        self,
        *,
        key: str,
        rank_maps: dict[str, dict[str, int]],
        min_scores: dict[str, float],
    ) -> bool:
        for channel in self._FUSION_CHANNELS:
            rank_score = self._rank_score(rank_maps[channel], key)
            if rank_score <= 0.0:
                continue
            threshold = min_scores.get(channel)
            if threshold is None or rank_score >= float(threshold):
                return True
        return False

    def _budget_channel_order(
        self,
        *,
        channel_results: list[dict[str, Any]],
        rank_map: dict[str, int],
        merged: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return sorted(
            channel_results,
            key=lambda item: (
                -_float_or_default(
                    merged.get(self._result_key(item), {}).get("exact_phrase_score"),
                    0.0,
                ),
                int(rank_map.get(self._result_key(item), len(channel_results) + 1)),
                self._result_key(item),
            ),
        )

    def _consume_budget_channel(
        self,
        *,
        channel: str,
        sorted_results: list[dict[str, Any]],
        rank_map: dict[str, int],
        budgets: dict[str, int],
        min_scores: dict[str, float],
        used: set[str],
        selected_keys: list[str],
        picked_by_channel: dict[str, int],
        rank_maps: dict[str, dict[str, int]],
    ) -> None:
        quota = int(budgets.get(channel, 0) or 0)
        if quota <= 0:
            return
        picked = 0
        threshold = min_scores.get(channel)
        for result in sorted_results:
            if picked >= quota:
                break
            key = self._result_key(result)
            if key in used:
                continue
            rank_score = self._rank_score(rank_map, key)
            if rank_score <= 0.0:
                continue
            if threshold is not None and rank_score < float(threshold):
                continue
            if not self._candidate_eligible(key=key, rank_maps=rank_maps, min_scores=min_scores):
                continue
            used.add(key)
            selected_keys.append(key)
            picked += 1
            try:
                picked_by_channel[channel] = int(picked_by_channel.get(channel, 0) or 0) + 1
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _fill_budgeted_prefix(
        self,
        *,
        all_sorted: list[dict[str, Any]],
        k_prefix: int,
        rank_maps: dict[str, dict[str, int]],
        min_scores: dict[str, float],
        used: set[str],
        selected_keys: list[str],
        picked_by_channel: dict[str, int],
    ) -> None:
        for item in all_sorted:
            if len(selected_keys) >= k_prefix:
                break
            key = self._result_key(item)
            if key in used:
                continue
            if not self._candidate_eligible(key=key, rank_maps=rank_maps, min_scores=min_scores):
                continue
            used.add(key)
            selected_keys.append(key)
            try:
                picked_by_channel["fill"] = int(picked_by_channel.get("fill", 0) or 0) + 1
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _record_budgeted_rrf_metrics(
        self,
        *,
        budgets: dict[str, int],
        min_scores: dict[str, float],
        picked_by_channel: dict[str, int],
        rank_maps: dict[str, dict[str, int]],
        keys: list[str],
        selected_keys: list[str],
        k_prefix: int,
        k0: int,
    ) -> None:
        try:
            if not isinstance(self._last_channel_metrics, dict):
                return
            eligible_total = 0
            for key in keys:
                if self._candidate_eligible(key=key, rank_maps=rank_maps, min_scores=min_scores):
                    eligible_total += 1
            budgets_out = dict(sorted((str(key), int(value or 0)) for key, value in (budgets or {}).items()))
            min_scores_out = dict(sorted((str(key), float(value or 0.0)) for key, value in (min_scores or {}).items()))
            picked_out = {
                channel: int(picked_by_channel.get(channel, 0) or 0)
                for channel in ("vector", "bm25", "lexical", "sparse", "fill")
            }
            self._last_channel_metrics["fusion_budgeted_rrf"] = {
                "k_prefix": int(k_prefix),
                "rrf_k": int(k0),
                "budgets": budgets_out,
                "min_scores": min_scores_out or None,
                "eligible_total": int(eligible_total),
                "selected_prefix": int(len(selected_keys)),
                "picked_by_channel": picked_out,
            }
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _merge_results_rrf(
        self,
        *,
        channel_results: dict[str, list[dict[str, Any]]],
        channel_norms: dict[str, dict[str, dict[str, Any]]],
        query: str | None,
        rrf_k: int | None,
    ) -> list[dict[str, Any]]:
        sorted_results = {
            channel: sorted(channel_results[channel], key=self._rank_sort_key) for channel in self._FUSION_CHANNELS
        }
        rank_maps = {channel: self._build_rank_map(sorted_results[channel]) for channel in self._FUSION_CHANNELS}
        k0 = max(1, int(rrf_k or 0) or int(getattr(self, "rrf_k", 60) or 60))
        merged, raw_scores, _keys = self._build_rrf_merged_items(
            channel_norms=channel_norms,
            rank_maps=rank_maps,
            k0=k0,
            strategy="rrf",
            include_rank_scores=False,
        )
        self._normalize_raw_scores(merged, raw_scores)
        self._apply_phrase_bonus(query=query, merged=merged)
        return self._apply_plugin_retrieval_policy(
            sorted(merged.values(), key=self._sort_key_rrf),
            query=query,
        )

    def _merge_results_budgeted_rrf(
        self,
        *,
        channel_results: dict[str, list[dict[str, Any]]],
        channel_norms: dict[str, dict[str, dict[str, Any]]],
        query: str | None,
        rrf_k: int | None,
        top_k: int | None,
    ) -> list[dict[str, Any]]:
        sorted_results = {
            channel: sorted(channel_results[channel], key=self._rank_sort_key) for channel in self._FUSION_CHANNELS
        }
        rank_maps = {channel: self._build_rank_map(sorted_results[channel]) for channel in self._FUSION_CHANNELS}
        k_prefix = max(1, int(top_k or 0) or int(getattr(self, "k", 0) or 0) or 10)
        budgets = self._resolve_budgeted_budgets(
            configured=self._coerce_budgets(getattr(self, "fusion_budgets", None)),
            channel_results=sorted_results,
            k_prefix=k_prefix,
        )
        min_scores = self._coerce_min_scores(getattr(self, "fusion_min_scores", None))
        k0 = max(1, int(rrf_k or 0) or int(getattr(self, "rrf_k", 60) or 60))
        merged, raw_scores, keys = self._build_rrf_merged_items(
            channel_norms=channel_norms,
            rank_maps=rank_maps,
            k0=k0,
            strategy="budgeted_rrf",
            include_rank_scores=True,
        )
        self._normalize_raw_scores(merged, raw_scores)
        self._apply_phrase_bonus(query=query, merged=merged)
        all_sorted = sorted(merged.values(), key=self._sort_key_budgeted_rrf)
        budget_sorted = {
            channel: self._budget_channel_order(
                channel_results=sorted_results[channel],
                rank_map=rank_maps[channel],
                merged=merged,
            )
            for channel in self._FUSION_CHANNELS
        }
        selected_keys: list[str] = []
        used: set[str] = set()
        picked_by_channel = {"vector": 0, "bm25": 0, "lexical": 0, "sparse": 0, "fill": 0}
        for channel in self._FUSION_CHANNELS:
            self._consume_budget_channel(
                channel=channel,
                sorted_results=budget_sorted[channel],
                rank_map=rank_maps[channel],
                budgets=budgets,
                min_scores=min_scores,
                used=used,
                selected_keys=selected_keys,
                picked_by_channel=picked_by_channel,
                rank_maps=rank_maps,
            )
        if len(selected_keys) < k_prefix:
            self._fill_budgeted_prefix(
                all_sorted=all_sorted,
                k_prefix=k_prefix,
                rank_maps=rank_maps,
                min_scores=min_scores,
                used=used,
                selected_keys=selected_keys,
                picked_by_channel=picked_by_channel,
            )
        selected_set = set(selected_keys)
        prefix = [item for item in all_sorted if self._result_key(item) in selected_set]
        rest = [item for item in all_sorted if self._result_key(item) not in selected_set]
        for index, item in enumerate(prefix, 1):
            item["fusion_budgeted_prefix_rank"] = int(index)
        self._record_budgeted_rrf_metrics(
            budgets=budgets,
            min_scores=min_scores,
            picked_by_channel=picked_by_channel,
            rank_maps=rank_maps,
            keys=keys,
            selected_keys=selected_keys,
            k_prefix=k_prefix,
            k0=k0,
        )
        return self._apply_plugin_retrieval_policy(prefix + rest, query=query)

    def _merge_results_weighted(
        self,
        *,
        channel_norms: dict[str, dict[str, dict[str, Any]]],
        query: str | None,
    ) -> list[dict[str, Any]] | None:
        weights_raw = self._coerce_weights(getattr(self, "fusion_weights", None))
        weight_sum = sum(float(value) for value in weights_raw.values())
        if weight_sum <= 0.0:
            return None
        weights = {key: float(value) / weight_sum for key, value in weights_raw.items()}
        merged: dict[str, dict[str, Any]] = {}
        for key in self._all_channel_keys(channel_norms):
            data = self._merged_channel_data(key=key, channel_norms=channel_norms)
            if not data:
                continue
            vector_score = self._channel_score(channel_norms, "vector", key)
            bm25_score = self._channel_score(channel_norms, "bm25", key)
            lexical_score = self._channel_score(channel_norms, "lexical", key)
            sparse_score = self._channel_score(channel_norms, "sparse", key)
            fused_score = (
                float(weights.get("vector", 0.0) or 0.0) * float(vector_score)
                + float(weights.get("bm25", 0.0) or 0.0) * float(bm25_score)
                + float(weights.get("lexical", 0.0) or 0.0) * float(lexical_score)
                + float(weights.get("sparse", 0.0) or 0.0) * float(sparse_score)
            )
            item = {
                **data,
                "vector_score": float(vector_score),
                "bm25_score": float(bm25_score),
                "lexical_score": float(lexical_score),
                "sparse_score": float(sparse_score),
                "fusion_strategy": "weighted",
                "score": float(fused_score),
            }
            self._attach_field_aware_signal(item, key=key, channel_norms=channel_norms)
            merged[key] = item
        try:
            if isinstance(self._last_channel_metrics, dict):
                weights_out = dict(sorted((key, round(float(value), 6)) for key, value in (weights or {}).items()))
                signature = ",".join([f"{key}:{weights_out.get(key, 0.0):.6f}" for key in sorted(weights_out.keys())])
                self._last_channel_metrics["fusion_weighted"] = {
                    "weights": weights_out,
                    "weights_hash": stable_hash(signature, length=16) if signature else None,
                }
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        return self._apply_plugin_retrieval_policy(
            sorted(merged.values(), key=self._sort_key_linear),
            query=query,
        )

    def _sort_key_linear(self, item: dict[str, Any]) -> tuple[float, float, float, float, float, str]:
        return (
            -float(item.get("score", 0.0) or 0.0),
            -float(item.get("vector_score", 0.0) or 0.0),
            -float(item.get("bm25_score", 0.0) or 0.0),
            -float(item.get("lexical_score", 0.0) or 0.0),
            -float(item.get("sparse_score", 0.0) or 0.0),
            self._result_key(item),
        )

    def _merge_results_linear(
        self,
        *,
        channel_norms: dict[str, dict[str, dict[str, Any]]],
        query: str | None,
        alpha: float,
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for key in self._all_channel_keys(channel_norms):
            data = self._merged_channel_data(key=key, channel_norms=channel_norms)
            if not data:
                continue
            vector_score = self._channel_score(channel_norms, "vector", key)
            bm25_score = self._channel_score(channel_norms, "bm25", key)
            lexical_score = self._channel_score(channel_norms, "lexical", key)
            sparse_score = self._channel_score(channel_norms, "sparse", key)
            keyword_score = max(float(bm25_score), float(lexical_score), float(sparse_score))
            has_vector = key in channel_norms["vector"]
            has_keyword = any(key in channel_norms[channel] for channel in ("bm25", "lexical", "sparse"))
            if has_vector and has_keyword:
                fused_score = alpha * float(vector_score) + (1 - alpha) * float(keyword_score)
            elif has_vector:
                fused_score = float(vector_score)
            else:
                fused_score = float(keyword_score)
            item = {
                **data,
                "vector_score": float(vector_score),
                "bm25_score": float(bm25_score),
                "lexical_score": float(lexical_score),
                "sparse_score": float(sparse_score),
                "fusion_strategy": "linear",
                "score": float(fused_score),
            }
            self._attach_field_aware_signal(item, key=key, channel_norms=channel_norms)
            merged[key] = item
        return self._apply_plugin_retrieval_policy(
            sorted(merged.values(), key=self._sort_key_linear),
            query=query,
        )

    def _merge_results(
        self,
        vector_results: list[dict[str, Any]],
        bm25_results: list[dict[str, Any]],
        lexical_results: list[dict[str, Any]] | None = None,
        sparse_results: list[dict[str, Any]] | None = None,
        query: str | None = None,
        alpha: float = 0.5,
        fusion_strategy: str | None = None,
        rrf_k: int | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Merge retrieval channel results into a single ranked list."""
        channel_results = {
            "vector": list(vector_results or []),
            "bm25": list(bm25_results or []),
            "lexical": list(lexical_results or []),
            "sparse": list(sparse_results or []),
        }
        runtime = self._build_fusion_runtime(query)
        channel_norms = {
            channel: self._normalize_channel_results(channel_results[channel], channel=channel, runtime=runtime)
            for channel in self._FUSION_CHANNELS
        }
        self._update_fusion_observability(vector_norm=channel_norms["vector"], runtime=runtime)
        fusion = (fusion_strategy or "linear").lower().strip()
        if fusion in ("rrf", "reciprocal_rank_fusion"):
            return self._merge_results_rrf(
                channel_results=channel_results,
                channel_norms=channel_norms,
                query=query,
                rrf_k=rrf_k,
            )
        if fusion in ("budgeted_rrf", "budget_rrf"):
            return self._merge_results_budgeted_rrf(
                channel_results=channel_results,
                channel_norms=channel_norms,
                query=query,
                rrf_k=rrf_k,
                top_k=top_k,
            )
        if fusion in ("weighted", "weighted_linear", "weighted_sum"):
            weighted = self._merge_results_weighted(channel_norms=channel_norms, query=query)
            if weighted is not None:
                return weighted
        return self._merge_results_linear(channel_norms=channel_norms, query=query, alpha=alpha)

    def _weight_rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4,
    ) -> list[dict[str, Any]]:
        """Vector score + keyword TF-IDF cosine linear weighting."""
        if not documents:
            return documents

        query_tokens = self._bm25_tokenize(query)
        doc_tokens_list = [self._bm25_tokenize(doc.get("content", "")) for doc in documents]

        doc_term_frequencies = [Counter(tokens) for tokens in doc_tokens_list]
        document_frequencies: Counter[str] = Counter()
        for term_frequencies in doc_term_frequencies:
            document_frequencies.update(term_frequencies.keys())
        if not document_frequencies:
            return documents

        doc_count = len(documents)
        token_idf = {
            token: math.log((1 + doc_count) / (1 + document_count)) + 1
            for token, document_count in document_frequencies.items()
        }

        def tfidf_vec(term_frequencies: Counter[str]) -> dict[str, float]:
            return {token: count * token_idf.get(token, 0.0) for token, count in term_frequencies.items()}

        query_vec = tfidf_vec(Counter(query_tokens))
        doc_vecs = [tfidf_vec(term_frequencies) for term_frequencies in doc_term_frequencies]

        def cosine(a: dict[str, float], b: dict[str, float]) -> float:
            if not a or not b:
                return 0.0
            common = set(a.keys()) & set(b.keys())
            num = sum(a[t] * b[t] for t in common)
            denom = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
            return num / denom if denom else 0.0

        keyword_scores = [cosine(query_vec, v) for v in doc_vecs]

        reranked: list[dict[str, Any]] = []
        phrase_boost_weight = max(0.0, float(getattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35) or 0.0))
        for doc, kw_score in zip(documents, keyword_scores, strict=False):
            vec_score = doc.get("vector_score", doc.get("score", 0.0))
            phrase = query_phrase_match(query, str(doc.get("content", "") or ""))
            phrase_score = float(phrase.get("score", 0.0) or 0.0)
            phrase_boost = phrase_score * phrase_boost_weight
            final_score = vector_weight * float(vec_score) + keyword_weight * float(kw_score) + phrase_boost
            new_doc = dict(doc)
            new_doc["keyword_score"] = float(kw_score)
            new_doc["exact_phrase_score"] = float(phrase_score)
            new_doc["exact_phrase_boost"] = float(phrase_boost)
            if phrase.get("matched_phrases"):
                new_doc["exact_phrase_matches"] = list(phrase.get("matched_phrases") or [])[:4]
            new_doc["score"] = float(final_score)
            reranked.append(new_doc)

        reranked.sort(key=lambda x: x["score"], reverse=True)
        return reranked

    def _mmr_doc_similarity(
        self,
        tokens_map: dict[int, set[str]],
        doc_a: dict[str, Any],
        doc_b: dict[str, Any],
    ) -> float:
        return self._jaccard(tokens_map.get(id(doc_a), set()), tokens_map.get(id(doc_b), set()))

    def _mmr_diversity_penalty(
        self,
        doc: dict[str, Any],
        selected: list[dict[str, Any]],
        tokens_map: dict[int, set[str]],
    ) -> float:
        if not selected:
            return 0.0
        similarities = [self._mmr_doc_similarity(tokens_map, doc, selected_doc) for selected_doc in selected]
        return max(similarities) if similarities else 0.0

    def _best_mmr_candidate(
        self,
        candidates: list[dict[str, Any]],
        selected: list[dict[str, Any]],
        *,
        tokens_map: dict[int, set[str]],
        lambda_mult: float,
    ) -> tuple[int, dict[str, Any]] | None:
        best: tuple[int, dict[str, Any]] | None = None
        best_score = -1e9
        for index, doc in enumerate(candidates):
            relevance = float(doc.get("score", 0.0))
            diversity_penalty = self._mmr_diversity_penalty(doc, selected, tokens_map)
            mmr_score = lambda_mult * relevance - (1 - lambda_mult) * diversity_penalty
            if mmr_score > best_score:
                best_score = mmr_score
                best = (index, doc)
        return best

    def _mmr_rerank(
        self,
        documents: list[dict[str, Any]],
        query: str,
        top_k: int,
        lambda_mult: float = 0.7,
    ) -> list[dict[str, Any]]:
        """
        Simple MMR (Maximal Marginal Relevance) reranking:
        max lambda*sim(query, doc) - (1-lambda)*max sim(doc, selected)
        Uses bag-of-words Jaccard approximation, lightweight with no extra dependencies.
        """
        if not documents:
            return documents

        lambda_mult = max(min(lambda_mult, 1.0), 0.0)
        selected: list[dict[str, Any]] = []
        candidates = list(documents)
        # Pre-cache tokens to avoid multiple tokenizations
        tokens_map = {id(doc): self._tokenize_for_similarity(doc.get("content", "")) for doc in candidates}

        while candidates and len(selected) < top_k:
            best = self._best_mmr_candidate(
                candidates,
                selected,
                tokens_map=tokens_map,
                lambda_mult=lambda_mult,
            )
            if best is None:
                break
            idx, doc = best
            selected.append(doc)
            candidates.pop(idx)

        return selected
