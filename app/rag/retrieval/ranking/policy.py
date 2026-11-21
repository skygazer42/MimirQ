"""Score, align and compact retrieval candidates using the selected plugin policy."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal, TypedDict

from app.rag.retrieval.ranking.policy_rules import (
    _as_dict,
    _metadata_terms,
    _metadata_value,
    _normalize_policy_match_text,
    _policy_float,
    _policy_string_list,
    _policy_value_fuzzy_overlaps_query,
    compact_high_confidence_items,
    retrieval_policy_anchor_mismatch_penalty,
    retrieval_policy_boost_score,
    retrieval_policy_query_terms,
    retrieval_policy_rerank_feature_score,
    retrieval_policy_response_compaction,
    retrieval_policy_value_intent_mismatch_penalty,
)
from app.types.document_metadata import metadata_text

logger = logging.getLogger("rag.retriever")

PluginRefForRecord = Callable[[dict[str, Any]], str | None]
MetadataLayersForRecord = Callable[[dict[str, Any]], list[dict[str, Any]] | tuple[dict[str, Any], ...]]
PolicyResolver = Callable[[str], dict[str, Any]]

POLICY_QUERY_EXPANSION_MATCH_BONUS = 0.08
POLICY_QUERY_EXPANSION_MATCH_BONUS_MAX = 0.16


class _DisabledAnchorBindingConfig(TypedDict):
    enabled: Literal[False]


class _AnchorBindingConfig(TypedDict):
    enabled: Literal[True]
    anchor_fields: tuple[str, ...]
    slot_fields: tuple[str, ...]
    anchor_match_bonus: float
    anchor_mismatch_penalty: float
    slot_only_penalty: float
    anchor_slot_match_bonus: float


_AnchorBindingRecordInfo = tuple[dict[str, Any], str, _AnchorBindingConfig, set[str], set[str], bool]


@dataclass(frozen=True)
class RetrievalPolicySignalScores:
    boost_field: float = 0.0
    query_expansion: float = 0.0
    rerank_feature: float = 0.0
    anchor_mismatch: float = 0.0
    value_intent_mismatch: float = 0.0

    @property
    def total(self) -> float:
        return self.positive_total - self.anchor_mismatch - self.value_intent_mismatch

    @property
    def positive_total(self) -> float:
        return self.boost_field + self.query_expansion + self.rerank_feature


def _anchor_binding_config(policy: dict[str, Any]) -> _AnchorBindingConfig | _DisabledAnchorBindingConfig:
    raw = _as_dict(policy.get("anchor_binding"))
    if raw.get("enabled") is not True:
        return {"enabled": False}
    anchor_fields = _policy_string_list(raw.get("anchor_fields"))
    if not anchor_fields:
        return {"enabled": False}
    anchor_mismatch_penalty = _policy_float(
        raw.get("anchor_mismatch_penalty", raw.get("slot_only_penalty")),
        default=0.0,
    )
    return {
        "enabled": True,
        "anchor_fields": anchor_fields,
        "slot_fields": _policy_string_list(raw.get("slot_fields")),
        "anchor_match_bonus": _policy_float(raw.get("anchor_match_bonus"), default=0.0),
        "anchor_mismatch_penalty": anchor_mismatch_penalty,
        "slot_only_penalty": _policy_float(raw.get("slot_only_penalty"), default=anchor_mismatch_penalty),
        "anchor_slot_match_bonus": _policy_float(raw.get("anchor_slot_match_bonus"), default=0.0),
    }


def _anchor_binding_values(
    metadata_layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    anchor_fields: tuple[str, ...],
) -> set[str]:
    out: set[str] = set()
    for layer in metadata_layers or ():
        meta = _as_dict(layer)
        for field in anchor_fields:
            for term in _metadata_terms(_metadata_value(meta, field)):
                normalized = _normalize_policy_match_text(term)
                if len(normalized) >= 3:
                    out.add(normalized)
    return out


def _anchor_binding_query_matches(query: str, values: set[str]) -> set[str]:
    query_text = _normalize_policy_match_text(query)
    if not query_text:
        return set()
    return {value for value in values if _policy_value_fuzzy_overlaps_query(query_text, value)}


def _policy_query_expansion_mapping_values(raw_mapping: dict[str, Any]) -> set[str]:
    raw_values: Any
    if isinstance(raw_mapping.get("values"), list | tuple | set):
        raw_values = raw_mapping.get("values")
    else:
        raw_values = [raw_mapping.get("value")]
    return {
        normalized
        for normalized in (_normalize_policy_match_text(value) for value in _metadata_terms(raw_values))
        if normalized
    }


def _slot_binding_query_matches(
    policy: dict[str, Any],
    metadata_layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    query: str,
    slot_fields: tuple[str, ...],
) -> bool:
    if not slot_fields:
        return False
    query_text = _normalize_policy_match_text(query)
    if not query_text:
        return False

    slot_values: set[str] = set()
    actual_values_by_field: dict[str, set[str]] = {}
    for layer in metadata_layers or ():
        meta = _as_dict(layer)
        for field in slot_fields:
            values = {
                normalized
                for normalized in (
                    _normalize_policy_match_text(value) for value in _metadata_terms(_metadata_value(meta, field))
                )
                if normalized
            }
            if values:
                actual_values_by_field.setdefault(field, set()).update(values)
                slot_values.update(values)

    for raw_mapping in policy.get("query_expansion_values") or ():
        mapping = _as_dict(raw_mapping)
        field = metadata_text(mapping, "metadata")
        if field not in slot_fields:
            continue
        actual_values = actual_values_by_field.get(field) or set()
        if not actual_values:
            continue
        expected_values = _policy_query_expansion_mapping_values(mapping)
        if not expected_values or not actual_values.intersection(expected_values):
            continue
        slot_values.update(
            normalized
            for normalized in (_normalize_policy_match_text(term) for term in _metadata_terms(mapping.get("terms")))
            if normalized
        )

    return any(_policy_value_fuzzy_overlaps_query(query_text, value) for value in slot_values)


def _anchor_binding_record_info(
    record: dict[str, Any],
    *,
    query: str,
    plugin_ref_for_record: PluginRefForRecord,
    metadata_layers_for_record: MetadataLayersForRecord,
    policy_resolver: PolicyResolver,
) -> _AnchorBindingRecordInfo | None:
    plugin_ref = plugin_ref_for_record(record)
    if plugin_ref is not None:
        plugin_ref = plugin_ref.strip()
    if not plugin_ref:
        return None
    policy = policy_resolver(plugin_ref)
    if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
        return None
    config = _anchor_binding_config(policy)
    if not config["enabled"]:
        return None
    metadata_layers = metadata_layers_for_record(record)
    anchor_values = _anchor_binding_values(
        metadata_layers,
        anchor_fields=config["anchor_fields"],
    )
    slot_matches = _slot_binding_query_matches(
        policy,
        metadata_layers,
        query=query,
        slot_fields=config["slot_fields"],
    )
    query_matches = _anchor_binding_query_matches(query, anchor_values)
    return record, plugin_ref, config, anchor_values, query_matches, slot_matches


def _anchor_binding_score(
    *,
    config: _AnchorBindingConfig,
    anchor_values: set[str],
    bound_anchors: set[str],
    query_matches: set[str],
    slot_matches: bool,
) -> float:
    if not bound_anchors:
        return 0.0
    if query_matches or anchor_values.intersection(bound_anchors):
        score = config["anchor_match_bonus"]
        if slot_matches:
            score += config["anchor_slot_match_bonus"]
        return score
    if slot_matches:
        return -(config["slot_only_penalty"])
    return -(config["anchor_mismatch_penalty"])


def record_retrieval_policy_anchor_binding_scores(
    records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    query: str,
    plugin_ref_for_record: PluginRefForRecord,
    metadata_layers_for_record: MetadataLayersForRecord,
    policy_resolver: PolicyResolver,
) -> dict[int, float]:
    """Return context-aware anchor binding adjustments for a candidate set.

    Plugins declare which metadata fields are entity anchors. The platform only
    binds records to anchors that are already present in the query and candidate
    set; records that only match generic slot wording are demoted when a bound
    anchor exists.
    """

    record_infos: list[_AnchorBindingRecordInfo] = []
    bound_anchors_by_ref: dict[str, set[str]] = {}
    for record in records or ():
        record_info = _anchor_binding_record_info(
            record,
            query=query,
            plugin_ref_for_record=plugin_ref_for_record,
            metadata_layers_for_record=metadata_layers_for_record,
            policy_resolver=policy_resolver,
        )
        if record_info is None:
            continue
        _record, plugin_ref, _config, _anchor_values, query_matches, _slot_matches = record_info
        if query_matches:
            bound_anchors_by_ref.setdefault(plugin_ref, set()).update(query_matches)
        record_infos.append(record_info)

    scores: dict[int, float] = {}
    for record, plugin_ref, config, anchor_values, query_matches, slot_matches in record_infos:
        bound_anchors = bound_anchors_by_ref.get(plugin_ref) or set()
        score = _anchor_binding_score(
            config=config,
            anchor_values=anchor_values,
            bound_anchors=bound_anchors,
            query_matches=query_matches,
            slot_matches=slot_matches,
        )
        if score:
            scores[id(record)] = score
    return scores


def retrieval_policy_query_expansion_bonus(
    policy: dict[str, Any],
    *,
    metadata_layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    query: str,
    base_bonus: float = POLICY_QUERY_EXPANSION_MATCH_BONUS,
    max_bonus: float = POLICY_QUERY_EXPANSION_MATCH_BONUS_MAX,
) -> float:
    query_text = _normalize_policy_match_text(query)
    if not query_text:
        return 0.0

    matches = 0
    for term in retrieval_policy_query_terms(policy, metadata_layers=metadata_layers):
        candidate = _normalize_policy_match_text(term)
        if len(candidate) < 3:
            continue
        if _policy_value_fuzzy_overlaps_query(query_text, candidate):
            matches += 1
    return min(float(base_bonus) * matches, float(max_bonus))


def retrieval_policy_signal_scores(
    policy: dict[str, Any],
    *,
    metadata_layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    query: str,
) -> RetrievalPolicySignalScores:
    if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
        return RetrievalPolicySignalScores()
    return RetrievalPolicySignalScores(
        boost_field=retrieval_policy_boost_score(
            policy,
            metadata_layers=metadata_layers,
            query=query,
        ),
        query_expansion=retrieval_policy_query_expansion_bonus(
            policy,
            metadata_layers=metadata_layers,
            query=query,
        ),
        rerank_feature=retrieval_policy_rerank_feature_score(
            policy,
            metadata_layers=metadata_layers,
            query=query,
        ),
        anchor_mismatch=retrieval_policy_anchor_mismatch_penalty(
            policy,
            metadata_layers=metadata_layers,
            query=query,
        ),
        value_intent_mismatch=retrieval_policy_value_intent_mismatch_penalty(
            policy,
            metadata_layers=metadata_layers,
            query=query,
        ),
    )


def record_retrieval_policy_bonus(
    record: dict[str, Any],
    *,
    query: str,
    plugin_ref_for_record: PluginRefForRecord,
    metadata_layers_for_record: MetadataLayersForRecord,
    policy_resolver: PolicyResolver,
) -> float:
    plugin_ref = plugin_ref_for_record(record)
    if plugin_ref is not None:
        plugin_ref = plugin_ref.strip()
    if not plugin_ref:
        return 0.0
    policy = policy_resolver(plugin_ref)
    if not policy:
        return 0.0
    return retrieval_policy_signal_scores(
        policy,
        metadata_layers=metadata_layers_for_record(record),
        query=query,
    ).total


def evaluate_records_retrieval_policy(
    records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    query: str,
    plugin_ref_for_record: PluginRefForRecord,
    metadata_layers_for_record: MetadataLayersForRecord,
    policy_resolver: PolicyResolver,
) -> tuple[dict[int, RetrievalPolicySignalScores], dict[str, Any]]:
    scores_by_record: dict[int, RetrievalPolicySignalScores] = {}
    plugin_refs: list[str] = []
    seen_refs: set[str] = set()
    policy_record_count = 0
    boosted_record_count = 0
    boost_field_record_count = 0
    query_expansion_record_count = 0
    rerank_feature_record_count = 0
    anchor_mismatch_record_count = 0
    for record in records or ():
        plugin_ref = plugin_ref_for_record(record)
        if plugin_ref is not None:
            plugin_ref = plugin_ref.strip()
        if not plugin_ref:
            continue
        policy = policy_resolver(plugin_ref)
        if not policy:
            continue
        policy_record_count += 1
        if plugin_ref not in seen_refs:
            seen_refs.add(plugin_ref)
            plugin_refs.append(plugin_ref)
        scores = retrieval_policy_signal_scores(
            policy,
            metadata_layers=metadata_layers_for_record(record),
            query=query,
        )
        scores_by_record[id(record)] = scores
        if scores.positive_total > 0:
            boosted_record_count += 1
        if scores.boost_field > 0:
            boost_field_record_count += 1
        if scores.query_expansion > 0:
            query_expansion_record_count += 1
        if scores.rerank_feature > 0:
            rerank_feature_record_count += 1
        if scores.anchor_mismatch > 0:
            anchor_mismatch_record_count += 1
    diagnostics = {
        "retrieval_policy_record_count": policy_record_count,
        "retrieval_policy_boosted_record_count": boosted_record_count,
        "retrieval_policy_boost_field_record_count": boost_field_record_count,
        "retrieval_policy_query_expansion_record_count": query_expansion_record_count,
        "retrieval_policy_rerank_feature_record_count": rerank_feature_record_count,
        "retrieval_policy_anchor_mismatch_record_count": anchor_mismatch_record_count,
        "retrieval_policy_plugin_refs": plugin_refs[:20],
    }
    return scores_by_record, diagnostics


def records_retrieval_policy_diagnostics(
    records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    query: str,
    plugin_ref_for_record: PluginRefForRecord,
    metadata_layers_for_record: MetadataLayersForRecord,
    policy_resolver: PolicyResolver,
) -> dict[str, Any]:
    _, diagnostics = evaluate_records_retrieval_policy(
        records,
        query=query,
        plugin_ref_for_record=plugin_ref_for_record,
        metadata_layers_for_record=metadata_layers_for_record,
        policy_resolver=policy_resolver,
    )
    return diagnostics


def filter_records_by_retrieval_policy_alignment(
    records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    query: str,
    plugin_ref_for_record: PluginRefForRecord,
    metadata_layers_for_record: MetadataLayersForRecord,
    policy_resolver: PolicyResolver,
) -> list[dict[str, Any]]:
    aligned: list[dict[str, Any]] = []
    evaluated = False
    for record in records or ():
        plugin_ref = plugin_ref_for_record(record)
        if plugin_ref is not None:
            plugin_ref = plugin_ref.strip()
        if not plugin_ref:
            continue
        policy = policy_resolver(plugin_ref)
        if not policy:
            continue
        scores = retrieval_policy_signal_scores(
            policy,
            metadata_layers=metadata_layers_for_record(record),
            query=query,
        )
        if scores.query_expansion > 0 or scores.value_intent_mismatch > 0:
            evaluated = True
        if scores.query_expansion > 0 and scores.value_intent_mismatch <= 0:
            aligned.append(record)
    if evaluated and aligned:
        return aligned
    return list(records or ())


class RetrievalPolicyMixin:
    def _compact_high_confidence_results(
        self,
        results: list[dict[str, Any]],
        *,
        top_k: int,
        stats: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        from app.infrastructure.config import settings
        from app.rag.retrieval.recall.common import _float_or_default

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

        enabled = bool(settings.RETRIEVAL_COMPACT_HIGH_CONFIDENCE_ENABLED or policy_config.get("enabled") is True)
        if stats is not None:
            stats.clear()
            stats["enabled"] = enabled
            stats["before"] = len(limited)
            stats["after"] = len(limited)
            stats["dropped"] = 0
            stats["source"] = "policy" if policy_config.get("enabled") is True else "settings"
            if policy_plugin_ref:
                stats["plugin_ref"] = policy_plugin_ref
        if not limited or not enabled:
            return limited

        min_top_score = policy_config.get("min_top_score", settings.RETRIEVAL_COMPACT_MIN_TOP_SCORE)
        relative_score_floor = policy_config.get(
            "relative_score_floor",
            settings.RETRIEVAL_COMPACT_RELATIVE_SCORE_FLOOR,
        )
        min_records = policy_config.get("min_records", settings.RETRIEVAL_COMPACT_MIN_RECORDS)
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
            stats["after"] = len(compacted)
            stats["dropped"] = max(0, len(limited) - len(compacted))
            stats["min_top_score"] = min_top_score
            stats["relative_score_floor"] = relative_score_floor
            stats["min_records"] = min_records
        return compacted

    @staticmethod
    def _result_metadata_layers(result: dict[str, Any]) -> list[dict[str, Any]]:
        from app.rag.retrieval.recall.common import _PLATFORM_METADATA_VIEW_KEYS

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
    def _result_plugin_ref(result: dict[str, Any]) -> str | None:
        from app.rag.retrieval.recall.common import _PIPELINE_PLUGIN_METADATA_KEYS

        for metadata in RetrievalPolicyMixin._result_metadata_layers(result):
            for key in _PIPELINE_PLUGIN_METADATA_KEYS:
                value = metadata_text(metadata, key)
                if value:
                    return value
        return None

    @staticmethod
    @lru_cache(maxsize=128)
    def _retrieval_policy_for_plugin_ref(plugin_ref: str) -> dict[str, Any]:
        from app.rag.retrieval.recall.common import NON_CRITICAL_RETRIEVER_FALLBACK_LOG

        ref = plugin_ref.strip()
        if not ref.startswith("plugin:"):
            return {}
        try:
            from app.rag.pipeline_plugins.registry import resolve_registered_plugin_descriptor

            descriptor = resolve_registered_plugin_descriptor(ref)
        except Exception as exc:  # noqa: BLE001
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
            return {}
        policy = descriptor.retrieval_policy
        if isinstance(policy, dict) and policy.get("schema") == "mimirq.retrieval_policy.v1":
            return dict(policy)
        return {}

    def _apply_plugin_retrieval_policy(
        self,
        results: list[dict[str, Any]],
        *,
        query: str | None,
    ) -> list[dict[str, Any]]:
        from app.infrastructure.config import settings
        from app.rag.retrieval.recall.common import _apply_exact_content_bonus_to_result, _float_or_default

        out = list(results or [])
        query_text = str((query if query is not None else "")).strip()
        if not out or not query_text:
            return out

        phrase_boost_weight = max(
            0.0,
            settings.RETRIEVAL_EXACT_PHRASE_RERANK_BOOST,
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
            result["retrieval_policy_bonus"] = round(bonus, 6)
            result["score"] = current_score + bonus
            adjusted += 1
            bonuses.append(bonus)

        if int(diagnostics.get("retrieval_policy_record_count") or 0) > 0 and isinstance(
            self._last_channel_metrics, dict
        ):
            diagnostics["score_adjusted_record_count"] = adjusted
            diagnostics["max_bonus"] = round(max(bonuses) if bonuses else 0.0, 6)
            diagnostics["min_bonus"] = round(min(bonuses) if bonuses else 0.0, 6)
            diagnostics["avg_bonus"] = round(sum(bonuses) / len(bonuses) if bonuses else 0.0, 6)
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


__all__ = [
    "MetadataLayersForRecord",
    "PluginRefForRecord",
    "PolicyResolver",
    "RetrievalPolicySignalScores",
    "evaluate_records_retrieval_policy",
    "filter_records_by_retrieval_policy_alignment",
    "record_retrieval_policy_anchor_binding_scores",
    "record_retrieval_policy_bonus",
    "records_retrieval_policy_diagnostics",
    "retrieval_policy_query_expansion_bonus",
    "retrieval_policy_signal_scores",
    "RetrievalPolicyMixin",
]
