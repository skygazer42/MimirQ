"""Dify record processing rules and operations."""

from typing import Any

from app.rag.retrieval.planner import compact_high_confidence_items, retrieval_policy_response_compaction
from app.services.dify_integration import answer_hints, policy_helpers, query_policy, record_helpers, record_ranking
from app.services.dify_integration.anchor_strength import (
    _record_has_any_requested_slot_field as _record_has_any_requested_slot_field,
)
from app.services.dify_integration.compaction import _compact_fast_answer_value as _compact_fast_answer_value
from app.services.dify_integration.compaction import _dify_fast_content_max_chars as _dify_fast_content_max_chars
from app.services.dify_integration.compaction import _dify_fast_response_top_k as _dify_fast_response_top_k
from app.services.dify_integration.compaction import (
    _dify_fast_total_content_max_chars as _dify_fast_total_content_max_chars,
)
from app.services.dify_integration.compaction import (
    _structured_label_values_from_content as _structured_label_values_from_content,
)
from app.services.dify_integration.policy_helpers import (
    fast_response_always_labels_for_policy_refs as _fast_response_always_labels_for_policy_refs,
)
from app.services.dify_integration.policy_helpers import record_plugin_ref as _record_plugin_ref
from app.services.dify_integration.policy_helpers import (
    requested_label_prefixes_for_policy_refs as _requested_label_prefixes_for_policy_refs,
)
from app.services.dify_integration.policy_helpers import response_hints_for_metadata as _response_hints_for_metadata
from app.services.dify_integration.scoring import _clamp_hint_value as _clamp_hint_value
from app.services.dify_integration.scoring import (
    _query_has_quoted_anchor_candidate as _query_has_quoted_anchor_candidate,
)


def _response_compaction_for_records(
    records: list[dict[str, Any]], *, policy_plugin_refs: tuple[str, ...] = ()
) -> dict[str, Any]:
    refs: list[str] = []
    seen: set[str] = set()
    for ref in policy_plugin_refs:
        text = ref.strip()
        if text and text not in seen:
            seen.add(text)
            refs.append(text)
    for record in records or ():
        text = _record_plugin_ref(record, fallback_plugin_refs=policy_plugin_refs)
        if text and text not in seen:
            seen.add(text)
            refs.append(text)
    for ref in refs:
        compaction = retrieval_policy_response_compaction(policy_helpers.retrieval_policy_for_plugin_ref(ref))
        if compaction["enabled"]:
            return compaction
    return {"enabled": False}


def _compact_fast_record_content(
    content: str, *, query: str, policy_plugin_refs: tuple[str, ...] = (), metadata: dict[str, Any] | None = None
) -> str:
    max_chars = _dify_fast_content_max_chars()
    body = content.strip()
    if not body:
        return body
    fields = _structured_label_values_from_content(body)
    metadata_hint_text, metadata_fields = _fast_metadata_fields(
        metadata, query=query, policy_plugin_refs=policy_plugin_refs
    )
    if metadata_fields:
        combined_fields = dict(fields)
        combined_fields.update(metadata_fields)
        fields = combined_fields
    labels = answer_hints._requested_fast_response_labels(query, fields, policy_plugin_refs=policy_plugin_refs)
    if labels:
        if "答案" in labels and fields.get("答案"):
            fields = dict(fields)
            fields["答案"] = _compact_fast_answer_value(fields["答案"], query=query, limit=max_chars)
        lines = _fast_compaction_lines(
            fields, metadata_fields, labels, policy_plugin_refs=policy_plugin_refs, max_chars=max_chars
        )
        compacted = "\n".join(lines).strip()
        if compacted:
            return _clamp_hint_value(compacted, limit=max_chars)
    if metadata_hint_text:
        return _clamp_hint_value(metadata_hint_text, limit=max_chars)
    return _clamp_hint_value(body, limit=max_chars)


def _compact_fast_records_for_response(
    records: list[dict[str, Any]], *, query: str, top_k: int, policy_plugin_refs: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    response_top_k = _dify_fast_response_top_k(top_k)
    total_budget = _dify_fast_total_content_max_chars()
    out: list[dict[str, Any]] = []
    used_chars = 0
    for record in list(records or [])[:response_top_k]:
        next_record = dict(record)
        metadata = dict(next_record.get("metadata") if isinstance(next_record.get("metadata"), dict) else {})
        original_content = next_record["content"]
        compacted_content = _compact_fast_record_content(
            original_content, query=query, policy_plugin_refs=policy_plugin_refs, metadata=metadata
        )
        remaining = total_budget - used_chars
        if remaining <= 0:
            break
        budget_trimmed = False
        if len(compacted_content) > remaining:
            if out:
                break
            compacted_content = _clamp_hint_value(compacted_content, limit=remaining - 3)
            budget_trimmed = compacted_content != original_content
        if compacted_content != original_content:
            metadata["dify_fast_compacted"] = True
            metadata["dify_original_content_chars"] = len(original_content)
        if budget_trimmed or used_chars + len(compacted_content) >= total_budget:
            metadata["dify_fast_context_budget_applied"] = True
        metadata["dify_fast_total_context_budget_chars"] = total_budget
        metadata["dify_fast_context_chars"] = len(compacted_content)
        next_record["content"] = compacted_content
        next_record["metadata"] = metadata
        used_chars += len(compacted_content)
        out.append(next_record)
    return out


def _compact_high_confidence_for_response(
    items: list[Any] | tuple[Any, ...],
    scores: list[float] | tuple[float, ...],
    raw_top_k: int,
    enabled: bool,
    min_top_score: float,
    relative_score_floor: float,
    min_items: int,
) -> tuple[Any, ...]:
    return compact_high_confidence_items(
        items,
        scores=scores,
        top_k=raw_top_k,
        enabled=enabled,
        min_top_score=min_top_score,
        relative_score_floor=relative_score_floor,
        min_items=min_items,
    )


def _compact_exact_anchor_answer_record(
    records: list[dict[str, Any]], *, query: str, policy_plugin_refs: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    requested_slots = query_policy._requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
    candidates = [
        record
        for record in records or []
        if record_ranking._record_exact_query_anchor_terms(record, query=query, policy_plugin_refs=policy_plugin_refs)
        and record_ranking._record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs)
        and record_ranking._record_covers_requested_policy_slots(
            record, requested_slots, policy_plugin_refs=policy_plugin_refs
        )
    ]
    if not candidates:
        return []
    record_ranking._sort_records_for_query(candidates, query=query, policy_plugin_refs=policy_plugin_refs)
    return [candidates[0]]


def _compact_mixed_intent_exact_anchor_records(
    records: list[dict[str, Any]], *, query: str, top_k: int, policy_plugin_refs: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    return record_helpers.compact_mixed_intent_exact_anchor_records(
        records,
        query=query,
        top_k=top_k,
        policy_plugin_refs=policy_plugin_refs,
        requested_policy_slot_specs_for_query=lambda raw_query, refs: (
            query_policy._requested_policy_slot_specs_for_query(raw_query, policy_plugin_refs=refs)
        ),
        composite_record_for_exact_anchor_slots=lambda items, raw_query, requested_slot_specs, refs: (
            record_ranking._composite_record_for_exact_anchor_slots(
                items, query=raw_query, requested_slot_specs=requested_slot_specs, policy_plugin_refs=refs
            )
        ),
        query_has_quoted_anchor_candidate=_query_has_quoted_anchor_candidate,
        record_exact_query_anchor_terms=lambda item, raw_query, refs: record_ranking._record_exact_query_anchor_terms(
            item, query=raw_query, policy_plugin_refs=refs
        ),
        record_content_is_answerful=lambda item, refs: record_ranking._record_content_is_answerful(
            item, policy_plugin_refs=refs
        ),
        records_have_confident_metadata_anchor=lambda items, raw_query, refs: (
            record_ranking._records_have_confident_metadata_anchor(items, query=raw_query, policy_plugin_refs=refs)
        ),
        record_has_any_requested_slot_field=_record_has_any_requested_slot_field,
        compact_exact_anchor_answer_record=lambda items, raw_query, refs: _compact_exact_anchor_answer_record(
            items, query=raw_query, policy_plugin_refs=refs
        ),
    )


def _compact_by_strong_question_anchor(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    if not records:
        return []
    if not record_ranking._record_has_strong_question_anchor(
        records[0],
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return records
    anchored = [
        record
        for record in records
        if record_ranking._record_has_strong_question_anchor(
            record,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
    ]
    return anchored or records


def _fast_metadata_fields(
    metadata: dict[str, Any] | None, *, query: str, policy_plugin_refs: tuple[str, ...]
) -> tuple[str, dict[str, str]]:
    if not isinstance(metadata, dict) or not metadata:
        return ("", {})
    response_hints = _response_hints_for_metadata(metadata, policy_plugin_refs=policy_plugin_refs)
    metadata_hints = answer_hints._metadata_answer_highlights(
        metadata, response_hints=response_hints, query=query, policy_plugin_refs=policy_plugin_refs
    )
    if not metadata_hints:
        return ("", {})
    hint_text = "\n".join(metadata_hints)
    return (hint_text, _structured_label_values_from_content(hint_text))


def _fast_compaction_lines(
    fields: dict[str, str],
    metadata_fields: dict[str, str],
    labels: tuple[str, ...],
    *,
    policy_plugin_refs: tuple[str, ...],
    max_chars: int,
) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    always_labels = set(_fast_response_always_labels_for_policy_refs(policy_plugin_refs))
    requested_labels = [
        label for label in labels if label not in always_labels and label not in {"问题", "答案"} and fields.get(label)
    ]
    for prefix in _requested_label_prefixes_for_policy_refs(policy_plugin_refs):
        value = metadata_fields.get(prefix)
        if not value and requested_labels:
            value = "、".join(requested_labels)
        if value:
            record_helpers._append_unique_line(lines, seen, f"{prefix}：{_clamp_hint_value(value, limit=max_chars)}")
    for label in labels:
        if fields.get(label):
            record_helpers._append_unique_line(
                lines, seen, f"{label}：{_clamp_hint_value(fields[label], limit=max_chars)}"
            )
    return lines
