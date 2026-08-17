"""Plugin-policy and response-compaction support for ``HybridRetriever``."""

from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.retrieval.hybrid.common import (
    _PIPELINE_PLUGIN_METADATA_KEYS,
    _PLATFORM_METADATA_VIEW_KEYS,
    NON_CRITICAL_RETRIEVER_FALLBACK_LOG,
    _apply_exact_content_bonus_to_result,
    _float_or_default,
)
from app.rag.retrieval.planner import compact_high_confidence_items, retrieval_policy_response_compaction
from app.rag.retrieval.plugin_policy import evaluate_records_retrieval_policy

logger = get_logger("rag.retriever")


class RetrievalPolicyMixin:
    def _compact_high_confidence_results(
        self,
        results: list[dict[str, Any]],
        *,
        top_k: int,
        stats: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        limited = list(results or [])[: max(1, int(top_k or 1))]
        policy_config: dict[str, Any] = {"enabled": False}
        policy_plugin_ref = ""
        for result in limited:
            plugin_ref = self._result_plugin_ref(result)
            if not plugin_ref:
                continue
            candidate_config = retrieval_policy_response_compaction(self._retrieval_policy_for_plugin_ref(plugin_ref))
            if candidate_config.get("enabled") is True:
                policy_config = candidate_config
                policy_plugin_ref = plugin_ref
                break

        enabled = bool(
            getattr(settings, "RETRIEVAL_COMPACT_HIGH_CONFIDENCE_ENABLED", False)
            or policy_config.get("enabled") is True
        )
        if stats is not None:
            stats.clear()
            stats["enabled"] = bool(enabled)
            stats["before"] = int(len(limited))
            stats["after"] = int(len(limited))
            stats["dropped"] = 0
            stats["source"] = "policy" if policy_config.get("enabled") is True else "settings"
            if policy_plugin_ref:
                stats["plugin_ref"] = policy_plugin_ref
        if not limited or not enabled:
            return limited

        min_top_score = float(
            policy_config.get("min_top_score", getattr(settings, "RETRIEVAL_COMPACT_MIN_TOP_SCORE", 0.8)) or 0.8
        )
        relative_score_floor = float(
            policy_config.get(
                "relative_score_floor",
                getattr(settings, "RETRIEVAL_COMPACT_RELATIVE_SCORE_FLOOR", 0.65),
            )
            or 0.65
        )
        min_records = int(policy_config.get("min_records", getattr(settings, "RETRIEVAL_COMPACT_MIN_RECORDS", 1)) or 1)
        compacted = list(
            compact_high_confidence_items(
                limited,
                scores=[_float_or_default(item.get("score"), 0.0) for item in limited],
                top_k=top_k,
                enabled=True,
                min_top_score=min_top_score,
                relative_score_floor=relative_score_floor,
                min_items=min_records,
            )
        )
        if stats is not None:
            stats["after"] = int(len(compacted))
            stats["dropped"] = int(max(0, len(limited) - len(compacted)))
            stats["min_top_score"] = float(min_top_score)
            stats["relative_score_floor"] = float(relative_score_floor)
            stats["min_records"] = int(min_records)
        return compacted

    @staticmethod
    def _result_metadata_layers(result: dict[str, Any]) -> list[dict[str, Any]]:
        meta = result.get("metadata")
        if not isinstance(meta, dict):
            return []
        layers = [meta]
        for key in _PLATFORM_METADATA_VIEW_KEYS:
            nested = meta.get(key)
            if isinstance(nested, dict) and nested:
                layers.append(nested)
        return layers

    @staticmethod
    def _result_plugin_ref(result: dict[str, Any]) -> str:
        for metadata in RetrievalPolicyMixin._result_metadata_layers(result):
            for key in _PIPELINE_PLUGIN_METADATA_KEYS:
                value = str(metadata.get(key) or "").strip()
                if value:
                    return value
        return ""

    @staticmethod
    @lru_cache(maxsize=128)
    def _retrieval_policy_for_plugin_ref(plugin_ref: str) -> dict[str, Any]:
        ref = str(plugin_ref or "").strip()
        if not ref.startswith("plugin:"):
            return {}
        try:
            from app.rag.pipeline_plugins.registry import resolve_registered_plugin_descriptor

            descriptor = resolve_registered_plugin_descriptor(ref)
        except Exception as exc:  # noqa: BLE001
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
            return {}
        policy = getattr(descriptor, "retrieval_policy", None)
        if isinstance(policy, dict) and policy.get("schema") == "mimirq.retrieval_policy.v1":
            return dict(policy)
        return {}

    def _apply_plugin_retrieval_policy(
        self,
        results: list[dict[str, Any]],
        *,
        query: str | None,
    ) -> list[dict[str, Any]]:
        out = list(results or [])
        query_text = str(query or "").strip()
        if not out or not query_text:
            return out

        phrase_boost_weight = max(
            0.0,
            float(getattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35) or 0.0),
        )
        exact_adjusted = 0
        for result in out:
            if _apply_exact_content_bonus_to_result(
                query=query_text,
                result=result,
                phrase_boost_weight=phrase_boost_weight,
            ):
                exact_adjusted += 1

        policy_scores, diagnostics = evaluate_records_retrieval_policy(
            out,
            query=query_text,
            plugin_ref_for_record=self._result_plugin_ref,
            metadata_layers_for_record=self._result_metadata_layers,
            policy_resolver=self._retrieval_policy_for_plugin_ref,
        )
        bonuses: list[float] = []
        adjusted = 0
        for result in out:
            scores = policy_scores.get(id(result))
            bonus = float(scores.total) if scores is not None else 0.0
            if not bonus:
                continue
            current_score = _float_or_default(result.get("score"), 0.0)
            result["retrieval_policy_bonus"] = round(float(bonus), 6)
            result["score"] = float(current_score) + float(bonus)
            adjusted += 1
            bonuses.append(float(bonus))

        if int(diagnostics.get("retrieval_policy_record_count") or 0) > 0 and isinstance(
            self._last_channel_metrics, dict
        ):
            diagnostics["score_adjusted_record_count"] = int(adjusted)
            diagnostics["max_bonus"] = round(float(max(bonuses) if bonuses else 0.0), 6)
            diagnostics["min_bonus"] = round(float(min(bonuses) if bonuses else 0.0), 6)
            diagnostics["avg_bonus"] = round(float(sum(bonuses) / len(bonuses)) if bonuses else 0.0, 6)
            self._last_channel_metrics["retrieval_policy"] = diagnostics

        if adjusted <= 0 and exact_adjusted <= 0:
            return out
        has_budgeted_prefix = any(item.get("fusion_budgeted_prefix_rank") is not None for item in out)
        if has_budgeted_prefix:
            return sorted(
                out,
                key=lambda item: (
                    0 if item.get("fusion_budgeted_prefix_rank") is not None else 1,
                    -_float_or_default(item.get("score"), 0.0),
                    self._result_key(item),
                ),
            )
        return sorted(out, key=lambda item: (-_float_or_default(item.get("score"), 0.0), self._result_key(item)))


__all__ = ["RetrievalPolicyMixin"]
