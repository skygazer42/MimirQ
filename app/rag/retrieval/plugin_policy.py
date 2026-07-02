from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.rag.retrieval.planner import (
    retrieval_policy_anchor_mismatch_penalty,
    retrieval_policy_boost_score,
    retrieval_policy_query_terms,
    retrieval_policy_rerank_feature_score,
    retrieval_policy_value_intent_mismatch_penalty,
)

PluginRefForRecord = Callable[[dict[str, Any]], str]
MetadataLayersForRecord = Callable[[dict[str, Any]], list[dict[str, Any]] | tuple[dict[str, Any], ...]]
PolicyResolver = Callable[[str], dict[str, Any]]

POLICY_QUERY_EXPANSION_MATCH_BONUS = 0.08
POLICY_QUERY_EXPANSION_MATCH_BONUS_MAX = 0.16


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


def _normalize_policy_match_text(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return "".join(char for char in text if char.isalnum())


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _policy_string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple | set):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def _metadata_value(meta: dict[str, Any], key: str) -> Any:
    if key in meta:
        return meta.get(key)
    if "." not in key:
        return meta.get(key)
    cur: Any = meta
    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _metadata_terms(value: Any) -> tuple[str, ...]:
    raw_items = value if isinstance(value, list | tuple | set) else [value]
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def _policy_float(value: Any, *, default: float, minimum: float = 0.0, maximum: float = 2.0) -> float:
    try:
        out = float(value if value is not None else default)
    except (TypeError, ValueError):
        out = float(default)
    return max(float(minimum), min(float(maximum), float(out)))


def _longest_common_substring_length(left: str, right: str) -> int:
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    best = 0
    for left_char in left:
        current = [0] * (len(right) + 1)
        for index, right_char in enumerate(right, start=1):
            if left_char != right_char:
                continue
            current[index] = previous[index - 1] + 1
            best = max(best, current[index])
        previous = current
    return best


def _policy_value_fuzzy_overlaps_query(query_text: str, value_text: str) -> bool:
    if not query_text or not value_text:
        return False
    if value_text in query_text or query_text in value_text:
        return True
    shortest = min(len(query_text), len(value_text))
    if shortest < 4:
        return False
    overlap = _longest_common_substring_length(query_text, value_text)
    return overlap >= 4 and (overlap / shortest) >= 0.72


def _anchor_binding_config(policy: dict[str, Any]) -> dict[str, Any]:
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
                    _normalize_policy_match_text(value)
                    for value in _metadata_terms(_metadata_value(meta, field))
                )
                if normalized
            }
            if values:
                actual_values_by_field.setdefault(field, set()).update(values)
                slot_values.update(values)

    for raw_mapping in policy.get("query_expansion_values") or ():
        mapping = _as_dict(raw_mapping)
        field = str(mapping.get("metadata") or "").strip()
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
            for normalized in (
                _normalize_policy_match_text(term)
                for term in _metadata_terms(mapping.get("terms"))
            )
            if normalized
        )

    return any(_policy_value_fuzzy_overlaps_query(query_text, value) for value in slot_values)


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

    record_infos: list[tuple[dict[str, Any], str, dict[str, Any], set[str], set[str], bool]] = []
    bound_anchors_by_ref: dict[str, set[str]] = {}
    for record in records or ():
        plugin_ref = str(plugin_ref_for_record(record) or "").strip()
        if not plugin_ref:
            continue
        policy = policy_resolver(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        config = _anchor_binding_config(policy)
        if not bool(config.get("enabled")):
            continue
        anchor_values = _anchor_binding_values(
            metadata_layers_for_record(record),
            anchor_fields=tuple(config.get("anchor_fields") or ()),
        )
        slot_matches = _slot_binding_query_matches(
            policy,
            metadata_layers_for_record(record),
            query=query,
            slot_fields=tuple(config.get("slot_fields") or ()),
        )
        query_matches = _anchor_binding_query_matches(query, anchor_values)
        if query_matches:
            bound_anchors_by_ref.setdefault(plugin_ref, set()).update(query_matches)
        record_infos.append((record, plugin_ref, config, anchor_values, query_matches, slot_matches))

    scores: dict[int, float] = {}
    for record, plugin_ref, config, anchor_values, query_matches, slot_matches in record_infos:
        bound_anchors = bound_anchors_by_ref.get(plugin_ref) or set()
        if not bound_anchors:
            continue
        score = 0.0
        if query_matches or anchor_values.intersection(bound_anchors):
            score += float(config.get("anchor_match_bonus") or 0.0)
            if slot_matches:
                score += float(config.get("anchor_slot_match_bonus") or 0.0)
        elif slot_matches:
            score -= float(config.get("slot_only_penalty") or 0.0)
        else:
            score -= float(config.get("anchor_mismatch_penalty") or 0.0)
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
    plugin_ref = str(plugin_ref_for_record(record) or "").strip()
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


def records_retrieval_policy_diagnostics(
    records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    query: str,
    plugin_ref_for_record: PluginRefForRecord,
    metadata_layers_for_record: MetadataLayersForRecord,
    policy_resolver: PolicyResolver,
) -> dict[str, Any]:
    plugin_refs: list[str] = []
    seen_refs: set[str] = set()
    policy_record_count = 0
    boosted_record_count = 0
    boost_field_record_count = 0
    query_expansion_record_count = 0
    rerank_feature_record_count = 0
    anchor_mismatch_record_count = 0
    for record in records or ():
        plugin_ref = str(plugin_ref_for_record(record) or "").strip()
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
    return {
        "retrieval_policy_record_count": policy_record_count,
        "retrieval_policy_boosted_record_count": boosted_record_count,
        "retrieval_policy_boost_field_record_count": boost_field_record_count,
        "retrieval_policy_query_expansion_record_count": query_expansion_record_count,
        "retrieval_policy_rerank_feature_record_count": rerank_feature_record_count,
        "retrieval_policy_anchor_mismatch_record_count": anchor_mismatch_record_count,
        "retrieval_policy_plugin_refs": plugin_refs[:20],
    }


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
        plugin_ref = str(plugin_ref_for_record(record) or "").strip()
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


__all__ = [
    "MetadataLayersForRecord",
    "PluginRefForRecord",
    "PolicyResolver",
    "RetrievalPolicySignalScores",
    "filter_records_by_retrieval_policy_alignment",
    "record_retrieval_policy_anchor_binding_scores",
    "record_retrieval_policy_bonus",
    "records_retrieval_policy_diagnostics",
    "retrieval_policy_query_expansion_bonus",
    "retrieval_policy_signal_scores",
]
