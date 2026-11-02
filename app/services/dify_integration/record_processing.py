"""Dify record processing rules and operations."""

from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.rag.retrieval.planner import compact_high_confidence_items, retrieval_policy_response_compaction
from app.rag.retrieval.plugin_policy import filter_records_by_retrieval_policy_alignment
from app.services.dify_integration import answer_hints, policy_helpers, query_policy, record_ranking
from app.services.dify_integration.anchor_strength import (
    _record_has_any_requested_slot_field as _record_has_any_requested_slot_field,
)
from app.services.dify_integration.common import _iter_record_metadata_layers as _iter_record_metadata_layers
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
from app.types.dify_integration import DifyExternalKnowledgeRecord


def _response_compaction_for_records(
    records: list[dict[str, Any]], *, policy_plugin_refs: tuple[str, ...] = ()
) -> dict[str, Any]:
    refs: list[str] = []
    seen: set[str] = set()
    for ref in policy_plugin_refs:
        text = str(ref or "").strip()
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
        if bool(compaction.get("enabled")):
            return compaction
    return {"enabled": False}


def _compact_fast_record_content(
    content: str, *, query: str, policy_plugin_refs: tuple[str, ...] = (), metadata: dict[str, Any] | None = None
) -> str:
    max_chars = _dify_fast_content_max_chars()
    body = str(content or "").strip()
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
        original_content = str(next_record.get("content") or "")
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
            compacted_content = _clamp_hint_value(compacted_content, limit=remaining)
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


def _compact_records_for_response(
    records: list[dict[str, Any]], *, query: str, top_k: int, policy_plugin_refs: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    compaction_enabled = settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED
    default_min_top_score = float(settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE or 0.7)
    default_relative_score_floor = float(settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR or 0.65)
    default_min_items = settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS or 1
    top_k_int = max(1, int(top_k or 1))
    mixed_intent_query = query_policy._query_has_mixed_intent_for_policy(query, policy_plugin_refs=policy_plugin_refs)
    if mixed_intent_query:
        exact_anchor_compacted = _mixed_intent_compaction(
            list(records or []), query=query, top_k=top_k, policy_plugin_refs=policy_plugin_refs
        )
        if exact_anchor_compacted is not None:
            return exact_anchor_compacted
    limited = list(records or [])[:top_k_int]
    if not limited:
        return []
    if mixed_intent_query:
        return limited
    strong_question_records = record_ranking._strong_question_anchor_records(
        limited, query=query, policy_plugin_refs=policy_plugin_refs
    )
    if any((record is limited[0] for record in strong_question_records)):
        return strong_question_records[:top_k_int]
    exact_anchor_answer = _compact_exact_anchor_answer_record(
        limited, query=query, policy_plugin_refs=policy_plugin_refs
    )
    if exact_anchor_answer:
        return exact_anchor_answer
    policy_compaction = _response_compaction_for_records(limited, policy_plugin_refs=policy_plugin_refs)
    limited = _apply_response_policy_compaction(
        limited,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
        compaction_enabled=compaction_enabled,
        policy_compaction=policy_compaction,
    )
    if not limited:
        return []
    policy_compaction_enabled = bool(policy_compaction.get("enabled"))
    compaction_scores = _response_compaction_scores(
        limited, query=query, policy_plugin_refs=policy_plugin_refs, policy_enabled=policy_compaction_enabled
    )
    compacted = _compact_high_confidence_for_response(
        limited,
        compaction_scores,
        top_k,
        compaction_enabled,
        float(policy_compaction.get("min_top_score") if policy_compaction_enabled else default_min_top_score or 0.7),
        float(
            policy_compaction.get("relative_score_floor")
            if policy_compaction_enabled
            else default_relative_score_floor or 0.65
        ),
        int(policy_compaction.get("min_records") if policy_compaction_enabled else default_min_items or 1),
    )
    return list(compacted)


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
    if not records:
        return []
    top_k_int = max(1, int(top_k or 1))
    requested_slots = query_policy._requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
    if requested_slots:
        composite = record_ranking._composite_record_for_exact_anchor_slots(
            records, query=query, requested_slot_specs=requested_slots, policy_plugin_refs=policy_plugin_refs
        )
        if composite is not None:
            return [composite]
    if _query_has_quoted_anchor_candidate(query):
        anchored_answer_records = _quoted_anchor_answer_records(
            records, query=query, policy_plugin_refs=policy_plugin_refs
        )
        if anchored_answer_records:
            return anchored_answer_records[:top_k_int]
    has_requested_slot_records = any(
        (_record_has_any_requested_slot_field(record, requested_slots) for record in records)
    )
    if not has_requested_slot_records:
        exact_anchor_answer = _compact_exact_anchor_answer_record(
            records, query=query, policy_plugin_refs=policy_plugin_refs
        )
        if exact_anchor_answer:
            return exact_anchor_answer[:top_k_int]
    if has_requested_slot_records:
        return []
    return _top_exact_anchor_record(
        records, query=query, requested_slots=requested_slots, policy_plugin_refs=policy_plugin_refs
    )[:top_k_int]


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


def _append_unique_line(lines: list[str], seen: set[str], line: str) -> None:
    value = str(line or "").strip()
    if not value or value in seen:
        return
    seen.add(value)
    lines.append(value)


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
            _append_unique_line(lines, seen, f"{prefix}：{_clamp_hint_value(value, limit=max_chars)}")
    for label in labels:
        if fields.get(label):
            _append_unique_line(lines, seen, f"{label}：{_clamp_hint_value(fields[label], limit=max_chars)}")
    return lines


def _quoted_anchor_answer_records(
    records: list[dict[str, Any]], *, query: str, policy_plugin_refs: tuple[str, ...]
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record_ranking._record_exact_query_anchor_terms(record, query=query, policy_plugin_refs=policy_plugin_refs)
        and (
            record_ranking._record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs)
            or record_ranking._records_have_confident_metadata_anchor(
                [record], query=query, policy_plugin_refs=policy_plugin_refs
            )
        )
    ]


def _top_exact_anchor_record(
    records: list[dict[str, Any]],
    *,
    query: str,
    requested_slots: tuple[tuple[str, str], ...],
    policy_plugin_refs: tuple[str, ...],
) -> list[dict[str, Any]]:
    top_record = records[0]
    if _record_has_any_requested_slot_field(top_record, requested_slots):
        return []
    if not record_ranking._record_exact_query_anchor_terms(
        top_record, query=query, policy_plugin_refs=policy_plugin_refs
    ):
        return []
    if record_ranking._record_content_is_answerful(top_record, policy_plugin_refs=policy_plugin_refs):
        return [top_record]
    if record_ranking._records_have_confident_metadata_anchor(
        [top_record], query=query, policy_plugin_refs=policy_plugin_refs
    ):
        return [top_record]
    return []


def _mixed_intent_compaction(
    records: list[dict[str, Any]], *, query: str, top_k: int, policy_plugin_refs: tuple[str, ...]
) -> list[dict[str, Any]] | None:
    compacted = _compact_mixed_intent_exact_anchor_records(
        records, query=query, top_k=top_k, policy_plugin_refs=policy_plugin_refs
    )
    if not compacted:
        return None
    supplements = [
        record
        for record in record_ranking._strong_question_anchor_records(
            records, query=query, policy_plugin_refs=policy_plugin_refs
        )
        if record not in compacted
    ]
    if len(compacted) == 1 and supplements and (not _query_has_quoted_anchor_candidate(query)):
        return None
    return compacted


def _apply_response_policy_compaction(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...],
    compaction_enabled: bool,
    policy_compaction: dict[str, Any],
) -> list[dict[str, Any]]:
    if not compaction_enabled or not bool(policy_compaction.get("enabled")):
        return records
    if record_ranking._record_has_strong_question_anchor(
        records[0], query=query, policy_plugin_refs=policy_plugin_refs
    ):
        return _compact_by_strong_question_anchor(records, query=query, policy_plugin_refs=policy_plugin_refs)
    aligned = filter_records_by_retrieval_policy_alignment(
        records,
        query=query,
        plugin_ref_for_record=lambda item: _record_plugin_ref(item, fallback_plugin_refs=policy_plugin_refs),
        metadata_layers_for_record=_iter_record_metadata_layers,
        policy_resolver=policy_helpers.retrieval_policy_for_plugin_ref,
    )
    return _compact_by_strong_question_anchor(aligned, query=query, policy_plugin_refs=policy_plugin_refs)


def _response_compaction_scores(
    records: list[dict[str, Any]], *, query: str, policy_plugin_refs: tuple[str, ...], policy_enabled: bool
) -> list[float]:
    if policy_enabled:
        return [
            record_ranking._record_rank_score(record, query=query, policy_plugin_refs=policy_plugin_refs)
            for record in records
        ]
    return [float(record.get("score") or 0.0) for record in records]


@dataclass(frozen=True)
class FinalizedRecords:
    records: list[DifyExternalKnowledgeRecord]
    ranked_records: list[dict[str, Any]]
    policy_diagnostics: dict[str, Any]


async def finalize_records(
    *,
    records: list[dict[str, Any]],
    query: str,
    top_k: int,
    response_top_k: int,
    policy_plugin_refs: tuple[str, ...],
    fast: bool,
    rerank: bool,
) -> FinalizedRecords:
    ranked = record_ranking._dedupe_records(records, query=query, policy_plugin_refs=policy_plugin_refs)
    record_ranking._sort_records_for_query(ranked, query=query, policy_plugin_refs=policy_plugin_refs)
    if rerank:
        ranked = await record_ranking._final_rerank_records_for_query(
            ranked,
            query=query,
            top_k=top_k,
            policy_plugin_refs=policy_plugin_refs,
        )
    diagnostics = record_ranking._records_retrieval_policy_diagnostics(
        ranked,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    compacted = _compact_records_for_response(
        ranked,
        query=query,
        top_k=response_top_k,
        policy_plugin_refs=policy_plugin_refs,
    )
    if fast:
        compacted = _compact_fast_records_for_response(
            compacted,
            query=query,
            top_k=response_top_k,
            policy_plugin_refs=policy_plugin_refs,
        )
    return FinalizedRecords(
        records=[DifyExternalKnowledgeRecord(**record) for record in compacted],
        ranked_records=ranked,
        policy_diagnostics=diagnostics,
    )
