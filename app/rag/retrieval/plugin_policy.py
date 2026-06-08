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
    "record_retrieval_policy_bonus",
    "records_retrieval_policy_diagnostics",
    "retrieval_policy_query_expansion_bonus",
    "retrieval_policy_signal_scores",
]
