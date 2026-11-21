"""Dify response record compaction and fast-answer content budgets."""

import re
from collections.abc import Callable
from typing import Any

from app.infrastructure.config import settings
from app.rag.retrieval.ranking.policy_rules import compact_high_confidence_items, retrieval_policy_response_compaction
from app.services.dify import answer_hints, query_policy, record_ranking
from app.services.dify import retrieval_policy as policy_helpers
from app.services.dify.anchor_strength import _record_has_any_requested_slot_field
from app.services.dify.common import _FAST_ANSWER_QUERY_STOP_TERMS, _normalize_match_term
from app.services.dify.retrieval_policy import (
    fast_response_always_labels_for_policy_refs as _fast_response_always_labels_for_policy_refs,
)
from app.services.dify.retrieval_policy import (
    record_plugin_ref as _record_plugin_ref,
)
from app.services.dify.retrieval_policy import (
    requested_label_prefixes_for_policy_refs as _requested_label_prefixes_for_policy_refs,
)
from app.services.dify.retrieval_policy import (
    response_hints_for_metadata as _response_hints_for_metadata,
)
from app.services.dify.scoring import (
    _clamp_hint_value,
    _field_line_parts,
    _iter_anchor_word_segments,
    _query_has_quoted_anchor_candidate,
    _quoted_query_anchor_terms,
)


def _dify_fast_candidate_top_k(top_k: int) -> int:
    configured = max(1, (settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_CANDIDATE_TOP_K_MAX or 3))
    return max(1, min(max(1, int(top_k or 1)), configured))


def _dify_fast_response_top_k(top_k: int) -> int:
    configured = max(1, (settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX or 2))
    return max(1, min(max(1, int(top_k or 1)), configured))


def _dify_fast_content_max_chars() -> int:
    return max(200, min(10000, (settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS or 1400)))


def _dify_fast_total_content_max_chars() -> int:
    return max(
        200,
        min(
            50000,
            (settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS or 2200),
        ),
    )


def _structured_label_values_from_content(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_label = ""
    for segment in re.split(r"\s*\|\s*|\n+", content):
        text = segment.strip()
        if not text:
            continue
        parts = _field_line_parts(text)
        if parts is None:
            if current_label and len(fields[current_label]) < _dify_fast_content_max_chars():
                fields[current_label] = f"{fields[current_label]}；{text}"
            continue
        label, value = parts
        current_label = label
        fields.setdefault(label, value)
    return fields


def _fast_answer_query_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        term = value.strip(" \t\r\n，。；;、：:？?！!（）()“”\"'《》「」")
        normalized = _normalize_match_term(term)
        if len(normalized) < 2 or normalized in seen or normalized in _FAST_ANSWER_QUERY_STOP_TERMS:
            return
        seen.add(normalized)
        terms.append(term)

    for anchor in _quoted_query_anchor_terms(query):
        add(anchor)
    for segment in _iter_anchor_word_segments(query):
        add(segment)
        for suffix in ("怎么申请", "如何申请", "怎么办理", "如何办理", "怎么查", "如何查", "是什么"):
            if segment.endswith(suffix):
                add(segment[: -len(suffix)])
                break
    terms.sort(key=lambda item: len(_normalize_match_term(item)), reverse=True)
    return tuple(terms)


def _fast_answer_snippet_segments(answer: str) -> list[str]:
    text = re.sub(r"\s+", " ", answer).strip()
    if not text:
        return []
    return [
        segment.strip()
        for segment in re.split(r"(?<=[。；;！？!?])\s*|\n+|(?<!\d)(?=[1-9][.)）])", text)
        if segment.strip()
    ]


def _compact_fast_answer_value(answer: str, *, query: str, limit: int) -> str:
    text = answer.strip()
    if len(text) <= limit:
        return text
    normalized_terms = tuple(
        _normalize_match_term(term) for term in _fast_answer_query_terms(query) if _normalize_match_term(term)
    )
    if not normalized_terms:
        return _clamp_hint_value(text, limit=limit)
    scored: list[tuple[int, int, str]] = []
    for index, segment in enumerate(_fast_answer_snippet_segments(text)):
        normalized_segment = _normalize_match_term(segment)
        matched = {term for term in normalized_terms if term and term in normalized_segment}
        if not matched:
            continue
        scored.append((index, sum(len(term) for term in matched), segment))
    if not scored:
        return _clamp_hint_value(text, limit=limit)
    target_limit = max(240, min(limit, 700))
    selected_indices = {index for index, _score, _segment in sorted(scored, key=lambda item: (-item[1], item[0]))[:6]}
    snippet = "".join(segment for index, _score, segment in scored if index in selected_indices).strip()
    if not snippet:
        return _clamp_hint_value(text, limit=limit)
    return _clamp_hint_value(snippet, limit=target_limit)


def _append_unique_line(lines: list[str], seen: set[str], line: str) -> None:
    value = line.strip()
    if not value or value in seen:
        return
    seen.add(value)
    lines.append(value)


def _quoted_anchor_answer_records(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...],
    record_exact_query_anchor_terms: Callable[[dict[str, Any], str, tuple[str, ...]], tuple[str, ...]],
    record_content_is_answerful: Callable[[dict[str, Any], tuple[str, ...]], bool],
    records_have_confident_metadata_anchor: Callable[[list[dict[str, Any]], str, tuple[str, ...]], bool],
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record_exact_query_anchor_terms(record, query, policy_plugin_refs)
        and (
            record_content_is_answerful(record, policy_plugin_refs)
            or records_have_confident_metadata_anchor([record], query, policy_plugin_refs)
        )
    ]


def _top_exact_anchor_record(
    records: list[dict[str, Any]],
    *,
    query: str,
    requested_slots: tuple[tuple[str, str], ...],
    policy_plugin_refs: tuple[str, ...],
    record_has_any_requested_slot_field: Callable[[dict[str, Any], tuple[tuple[str, str], ...]], bool],
    record_exact_query_anchor_terms: Callable[[dict[str, Any], str, tuple[str, ...]], tuple[str, ...]],
    record_content_is_answerful: Callable[[dict[str, Any], tuple[str, ...]], bool],
    records_have_confident_metadata_anchor: Callable[[list[dict[str, Any]], str, tuple[str, ...]], bool],
) -> list[dict[str, Any]]:
    top_record = records[0]
    if record_has_any_requested_slot_field(top_record, requested_slots):
        return []
    if not record_exact_query_anchor_terms(top_record, query, policy_plugin_refs):
        return []
    if record_content_is_answerful(top_record, policy_plugin_refs):
        return [top_record]
    if records_have_confident_metadata_anchor([top_record], query, policy_plugin_refs):
        return [top_record]
    return []


def compact_mixed_intent_exact_anchor_records(
    records: list[dict[str, Any]],
    *,
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
    requested_policy_slot_specs_for_query: Callable[[str, tuple[str, ...]], tuple[tuple[str, str], ...]],
    composite_record_for_exact_anchor_slots: Callable[
        [list[dict[str, Any]], str, tuple[tuple[str, str], ...], tuple[str, ...]],
        dict[str, Any] | None,
    ],
    query_has_quoted_anchor_candidate: Callable[[str], bool],
    record_exact_query_anchor_terms: Callable[[dict[str, Any], str, tuple[str, ...]], tuple[str, ...]],
    record_content_is_answerful: Callable[[dict[str, Any], tuple[str, ...]], bool],
    records_have_confident_metadata_anchor: Callable[[list[dict[str, Any]], str, tuple[str, ...]], bool],
    record_has_any_requested_slot_field: Callable[[dict[str, Any], tuple[tuple[str, str], ...]], bool],
    compact_exact_anchor_answer_record: Callable[[list[dict[str, Any]], str, tuple[str, ...]], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if not records:
        return []
    top_k_int = max(1, int(top_k or 1))
    requested_slots = requested_policy_slot_specs_for_query(query, policy_plugin_refs)

    if requested_slots:
        composite = composite_record_for_exact_anchor_slots(records, query, requested_slots, policy_plugin_refs)
        if composite is not None:
            return [composite]

    if query_has_quoted_anchor_candidate(query):
        anchored_answer_records = _quoted_anchor_answer_records(
            records,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
            record_exact_query_anchor_terms=record_exact_query_anchor_terms,
            record_content_is_answerful=record_content_is_answerful,
            records_have_confident_metadata_anchor=records_have_confident_metadata_anchor,
        )
        if anchored_answer_records:
            return anchored_answer_records[:top_k_int]

    has_requested_slot_records = any(record_has_any_requested_slot_field(record, requested_slots) for record in records)
    if not has_requested_slot_records:
        exact_anchor_answer = compact_exact_anchor_answer_record(records, query, policy_plugin_refs)
        if exact_anchor_answer:
            return exact_anchor_answer[:top_k_int]

    if has_requested_slot_records:
        return []
    return _top_exact_anchor_record(
        records,
        query=query,
        requested_slots=requested_slots,
        policy_plugin_refs=policy_plugin_refs,
        record_has_any_requested_slot_field=record_has_any_requested_slot_field,
        record_exact_query_anchor_terms=record_exact_query_anchor_terms,
        record_content_is_answerful=record_content_is_answerful,
        records_have_confident_metadata_anchor=records_have_confident_metadata_anchor,
    )[:top_k_int]


def _mixed_intent_compaction(
    records: list[dict[str, Any]],
    *,
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...],
    compact_mixed_intent_exact_anchor_records: Callable[
        [list[dict[str, Any]], str, int, tuple[str, ...]],
        list[dict[str, Any]],
    ],
    strong_question_anchor_records: Callable[
        [list[dict[str, Any]], str, tuple[str, ...]],
        list[dict[str, Any]],
    ],
    query_has_quoted_anchor_candidate: Callable[[str], bool],
) -> list[dict[str, Any]] | None:
    compacted = compact_mixed_intent_exact_anchor_records(records, query, top_k, policy_plugin_refs)
    if not compacted:
        return None
    supplements = [
        record
        for record in strong_question_anchor_records(records, query, policy_plugin_refs)
        if record not in compacted
    ]
    if len(compacted) == 1 and supplements and not query_has_quoted_anchor_candidate(query):
        return None
    return compacted


def _apply_response_policy_compaction(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...],
    compaction_enabled: bool,
    policy_compaction: dict[str, Any],
    record_has_strong_question_anchor: Callable[[dict[str, Any], str, tuple[str, ...]], bool],
    compact_by_strong_question_anchor: Callable[
        [list[dict[str, Any]], str, tuple[str, ...]],
        list[dict[str, Any]],
    ],
    filter_records_by_retrieval_policy_alignment: Callable[
        [list[dict[str, Any]], str, tuple[str, ...]],
        list[dict[str, Any]],
    ],
) -> list[dict[str, Any]]:
    if not compaction_enabled or not bool(policy_compaction.get("enabled")):
        return records
    if record_has_strong_question_anchor(records[0], query, policy_plugin_refs):
        return compact_by_strong_question_anchor(records, query, policy_plugin_refs)
    aligned = filter_records_by_retrieval_policy_alignment(records, query, policy_plugin_refs)
    return compact_by_strong_question_anchor(aligned, query, policy_plugin_refs)


def _response_compaction_scores(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...],
    policy_enabled: bool,
    record_rank_score: Callable[[dict[str, Any], str, tuple[str, ...]], float],
) -> list[float]:
    if policy_enabled:
        return [record_rank_score(record, query, policy_plugin_refs) for record in records]
    return [float(record.get("score") or 0.0) for record in records]


def compact_records_for_response(
    records: list[dict[str, Any]],
    *,
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
    query_has_mixed_intent_for_policy: Callable[[str, tuple[str, ...]], bool],
    compact_mixed_intent_exact_anchor_records: Callable[
        [list[dict[str, Any]], str, int, tuple[str, ...]],
        list[dict[str, Any]],
    ],
    strong_question_anchor_records: Callable[[list[dict[str, Any]], str, tuple[str, ...]], list[dict[str, Any]]],
    query_has_quoted_anchor_candidate: Callable[[str], bool],
    compact_exact_anchor_answer_record: Callable[[list[dict[str, Any]], str, tuple[str, ...]], list[dict[str, Any]]],
    compaction_enabled: bool,
    response_compaction_for_records: Callable[[list[dict[str, Any]], tuple[str, ...]], dict[str, Any]],
    record_has_strong_question_anchor: Callable[[dict[str, Any], str, tuple[str, ...]], bool],
    compact_by_strong_question_anchor: Callable[[list[dict[str, Any]], str, tuple[str, ...]], list[dict[str, Any]]],
    filter_records_by_retrieval_policy_alignment: Callable[
        [list[dict[str, Any]], str, tuple[str, ...]], list[dict[str, Any]]
    ],
    record_rank_score: Callable[[dict[str, Any], str, tuple[str, ...]], float],
    compact_high_confidence_items: Callable[
        [list[dict[str, Any]], list[float], int, bool, float, float, int], list[dict[str, Any]]
    ],
    default_min_top_score: float,
    default_relative_score_floor: float,
    default_min_items: int,
) -> list[dict[str, Any]]:
    top_k_int = max(1, int(top_k or 1))
    mixed_intent_query = query_has_mixed_intent_for_policy(query, policy_plugin_refs)
    if mixed_intent_query:
        exact_anchor_compacted = _mixed_intent_compaction(
            list(records or []),
            query=query,
            top_k=top_k,
            policy_plugin_refs=policy_plugin_refs,
            compact_mixed_intent_exact_anchor_records=compact_mixed_intent_exact_anchor_records,
            strong_question_anchor_records=strong_question_anchor_records,
            query_has_quoted_anchor_candidate=query_has_quoted_anchor_candidate,
        )
        if exact_anchor_compacted is not None:
            return exact_anchor_compacted

    limited = list(records or [])[:top_k_int]
    if not limited:
        return []
    if mixed_intent_query:
        return limited
    strong_question_records = strong_question_anchor_records(limited, query, policy_plugin_refs)
    if any(record is limited[0] for record in strong_question_records):
        return strong_question_records[:top_k_int]
    exact_anchor_answer = compact_exact_anchor_answer_record(limited, query, policy_plugin_refs)
    if exact_anchor_answer:
        return exact_anchor_answer
    policy_compaction = response_compaction_for_records(limited, policy_plugin_refs)
    limited = _apply_response_policy_compaction(
        limited,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
        compaction_enabled=compaction_enabled,
        policy_compaction=policy_compaction,
        record_has_strong_question_anchor=record_has_strong_question_anchor,
        compact_by_strong_question_anchor=compact_by_strong_question_anchor,
        filter_records_by_retrieval_policy_alignment=filter_records_by_retrieval_policy_alignment,
    )
    if not limited:
        return []
    policy_compaction_enabled = bool(policy_compaction.get("enabled"))
    compaction_scores = _response_compaction_scores(
        limited,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
        policy_enabled=policy_compaction_enabled,
        record_rank_score=record_rank_score,
    )
    compacted = compact_high_confidence_items(
        limited,
        compaction_scores,
        top_k,
        compaction_enabled,
        float(policy_compaction.get("min_top_score") if policy_compaction_enabled else default_min_top_score),
        float(
            policy_compaction.get("relative_score_floor") if policy_compaction_enabled else default_relative_score_floor
        ),
        int(policy_compaction.get("min_records") if policy_compaction_enabled else default_min_items or 1),
    )
    return list(compacted)


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
    compacted = ""
    if labels:
        if "答案" in labels and fields.get("答案"):
            fields = dict(fields)
            fields["答案"] = _compact_fast_answer_value(fields["答案"], query=query, limit=max_chars)
        lines = _fast_compaction_lines(
            fields, metadata_fields, labels, policy_plugin_refs=policy_plugin_refs, max_chars=max_chars
        )
        compacted = "\n".join(lines).strip()
    selected = compacted or metadata_hint_text or body
    return _clamp_hint_value(selected, limit=max_chars - 3) if len(selected) > max_chars else selected


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
    return compact_mixed_intent_exact_anchor_records(
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
            _append_unique_line(lines, seen, f"{prefix}：{_clamp_hint_value(value, limit=max_chars)}")
    for label in labels:
        if fields.get(label):
            _append_unique_line(lines, seen, f"{label}：{_clamp_hint_value(fields[label], limit=max_chars)}")
    return lines
