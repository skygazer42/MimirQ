
from collections.abc import Callable
from typing import Any


def response_compaction_for_records(
    records: list[dict[str, Any]],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
    record_plugin_ref: Callable[[dict[str, Any], tuple[str, ...]], str],
    policy_resolver: Callable[[str], dict[str, Any]],
    response_compaction_resolver: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    refs: list[str] = []
    seen: set[str] = set()
    for ref in policy_plugin_refs:
        text = str(ref or "").strip()
        if text and text not in seen:
            seen.add(text)
            refs.append(text)
    for record in records or ():
        text = record_plugin_ref(record, policy_plugin_refs)
        if text and text not in seen:
            seen.add(text)
            refs.append(text)
    for ref in refs:
        compaction = response_compaction_resolver(policy_resolver(ref))
        if bool(compaction.get("enabled")):
            return compaction
    return {"enabled": False}


def record_answerfulness_score(
    record: dict[str, Any],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
    record_has_answer_evidence: Callable[[dict[str, Any], str, tuple[str, ...]], bool],
    record_is_anchor_only_qa: Callable[[dict[str, Any], str, tuple[str, ...]], bool],
    answerful_record_bonus: float,
    anchor_only_qa_record_penalty: float,
) -> float:
    content = str(record.get("content") or "").strip()
    if not content:
        return 0.0
    if record_has_answer_evidence(record, content, policy_plugin_refs):
        return answerful_record_bonus
    if record_is_anchor_only_qa(record, content, policy_plugin_refs):
        return -anchor_only_qa_record_penalty
    return 0.0


def record_rank_score(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
    record_metadata_anchor_bonus: Callable[[dict[str, Any], str], float],
    record_intent_bonus: Callable[[dict[str, Any], str, tuple[str, ...]], float],
    record_exact_primary_alias_bonus: Callable[[dict[str, Any], str], float],
    record_url_evidence_bonus: Callable[[dict[str, Any], str], float],
    record_question_intent_bonus: Callable[[dict[str, Any], str, tuple[str, ...]], float],
    record_answerfulness_score: Callable[[dict[str, Any], tuple[str, ...]], float],
    record_mixed_intent_subquery_bonus: Callable[[dict[str, Any], str, tuple[str, ...]], float],
    record_retrieval_policy_bonus: Callable[[dict[str, Any], str, tuple[str, ...]], float],
) -> float:
    return (
        float(record.get("score") or 0.0)
        + record_metadata_anchor_bonus(record, query)
        + record_intent_bonus(record, query, policy_plugin_refs)
        + record_exact_primary_alias_bonus(record, query)
        + record_url_evidence_bonus(record, query)
        + record_question_intent_bonus(record, query, policy_plugin_refs)
        + record_answerfulness_score(record, policy_plugin_refs)
        + record_mixed_intent_subquery_bonus(record, query, policy_plugin_refs)
        + record_retrieval_policy_bonus(record, query, policy_plugin_refs)
    )


def compact_fast_record_content(
    content: str,
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
    max_chars: int,
    structured_label_values_from_content: Callable[[str], dict[str, str]],
    response_hints_for_metadata: Callable[[dict[str, Any], tuple[str, ...]], dict[str, Any]],
    metadata_answer_highlights: Callable[[dict[str, Any], dict[str, Any], str, tuple[str, ...]], list[str]],
    requested_fast_response_labels: Callable[[str, dict[str, str], tuple[str, ...]], tuple[str, ...]],
    fast_response_always_labels_for_policy_refs: Callable[[tuple[str, ...]], tuple[str, ...]],
    requested_label_prefixes_for_policy_refs: Callable[[tuple[str, ...]], tuple[str, ...]],
    clamp_hint_value: Callable[[str, int], str],
    compact_fast_answer_value: Callable[[str, str, int], str],
) -> str:
    body = str(content or "").strip()
    if not body:
        return body
    fields = structured_label_values_from_content(body)
    metadata_hint_text = ""
    metadata_fields: dict[str, str] = {}
    if isinstance(metadata, dict) and metadata:
        response_hints = response_hints_for_metadata(metadata, policy_plugin_refs)
        metadata_hints = metadata_answer_highlights(metadata, response_hints, query, policy_plugin_refs)
        if metadata_hints:
            metadata_hint_text = "\n".join(metadata_hints)
            metadata_fields = structured_label_values_from_content(metadata_hint_text)
    if metadata_fields:
        combined_fields = dict(fields)
        combined_fields.update(metadata_fields)
        fields = combined_fields
    labels = requested_fast_response_labels(query, fields, policy_plugin_refs)
    if labels:
        if "答案" in labels and fields.get("答案"):
            fields = dict(fields)
            fields["答案"] = compact_fast_answer_value(fields["答案"], query, max_chars)
        lines: list[str] = []
        seen_lines: set[str] = set()

        def add_line(line: str) -> None:
            value = str(line or "").strip()
            if not value or value in seen_lines:
                return
            seen_lines.add(value)
            lines.append(value)

        always_labels = set(fast_response_always_labels_for_policy_refs(policy_plugin_refs))
        requested_labels = [
            label
            for label in labels
            if label not in always_labels and label not in {"问题", "答案"} and fields.get(label)
        ]
        for prefix in requested_label_prefixes_for_policy_refs(policy_plugin_refs):
            value = metadata_fields.get(prefix)
            if not value and requested_labels:
                value = "、".join(requested_labels)
            if value:
                add_line(f"{prefix}：{clamp_hint_value(value, max_chars)}")
        for label in labels:
            if fields.get(label):
                add_line(f"{label}：{clamp_hint_value(fields[label], max_chars)}")
        compacted = "\n".join(lines).strip()
        if compacted:
            return clamp_hint_value(compacted, max_chars)
    if metadata_hint_text:
        return clamp_hint_value(metadata_hint_text, max_chars)
    return clamp_hint_value(body, max_chars)


def compact_fast_records_for_response(
    records: list[dict[str, Any]],
    *,
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
    response_top_k: int,
    total_budget: int,
    compact_fast_record_content: Callable[[str, str, tuple[str, ...], dict[str, Any] | None], str],
    clamp_hint_value: Callable[[str, int], str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    used_chars = 0
    for record in list(records or [])[:response_top_k]:
        next_record = dict(record)
        metadata = dict(next_record.get("metadata") if isinstance(next_record.get("metadata"), dict) else {})
        original_content = str(next_record.get("content") or "")
        compacted_content = compact_fast_record_content(
            original_content,
            query,
            policy_plugin_refs,
            metadata,
        )
        remaining = total_budget - used_chars
        if remaining <= 0:
            break
        budget_trimmed = False
        if len(compacted_content) > remaining:
            if out:
                break
            compacted_content = clamp_hint_value(compacted_content, remaining)
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


def strong_question_anchor_records(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
    record_has_strong_question_anchor: Callable[[dict[str, Any], str, tuple[str, ...]], bool],
    record_content_is_answerful: Callable[[dict[str, Any], tuple[str, ...]], bool],
) -> list[dict[str, Any]]:
    return [
        record
        for record in records or []
        if record_has_strong_question_anchor(record, query, policy_plugin_refs)
        and record_content_is_answerful(record, policy_plugin_refs)
    ]


def compact_exact_anchor_answer_record(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
    record_exact_query_anchor_terms: Callable[[dict[str, Any], str, tuple[str, ...]], tuple[str, ...]],
    record_content_is_answerful: Callable[[dict[str, Any], tuple[str, ...]], bool],
    requested_policy_slot_specs_for_query: Callable[[str, tuple[str, ...]], tuple[tuple[str, str], ...]],
    record_covers_requested_policy_slots: Callable[
        [dict[str, Any], tuple[tuple[str, str], ...], tuple[str, ...]],
        bool,
    ],
    sort_records_for_query: Callable[[list[dict[str, Any]], str, tuple[str, ...]], None],
) -> list[dict[str, Any]]:
    requested_slots = requested_policy_slot_specs_for_query(query, policy_plugin_refs)
    candidates = [
        record
        for record in records or []
        if record_exact_query_anchor_terms(record, query, policy_plugin_refs)
        and record_content_is_answerful(record, policy_plugin_refs)
        and record_covers_requested_policy_slots(record, requested_slots, policy_plugin_refs)
    ]
    if not candidates:
        return []
    sort_records_for_query(candidates, query, policy_plugin_refs)
    return [candidates[0]]


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
        anchored_answer_records = [
            record
            for record in records
            if record_exact_query_anchor_terms(record, query, policy_plugin_refs)
            and (
                record_content_is_answerful(record, policy_plugin_refs)
                or records_have_confident_metadata_anchor([record], query, policy_plugin_refs)
            )
        ]
        if anchored_answer_records:
            return anchored_answer_records[:top_k_int]

    has_requested_slot_records = any(record_has_any_requested_slot_field(record, requested_slots) for record in records)
    if not has_requested_slot_records:
        exact_anchor_answer = compact_exact_anchor_answer_record(records, query, policy_plugin_refs)
        if exact_anchor_answer:
            return exact_anchor_answer[:top_k_int]

    top_record = records[0]
    if has_requested_slot_records:
        return []
    if record_has_any_requested_slot_field(top_record, requested_slots):
        return []
    if not record_exact_query_anchor_terms(top_record, query, policy_plugin_refs):
        return []
    if not (
        record_content_is_answerful(top_record, policy_plugin_refs)
        or records_have_confident_metadata_anchor([top_record], query, policy_plugin_refs)
    ):
        return []
    return [top_record][:top_k_int]


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
    filter_records_by_retrieval_policy_alignment: Callable[[list[dict[str, Any]], str, tuple[str, ...]], list[dict[str, Any]]],
    record_rank_score: Callable[[dict[str, Any], str, tuple[str, ...]], float],
    compact_high_confidence_items: Callable[[list[dict[str, Any]], list[float], int, bool, float, float, int], list[dict[str, Any]]],
    default_min_top_score: float,
    default_relative_score_floor: float,
    default_min_items: int,
) -> list[dict[str, Any]]:
    top_k_int = max(1, int(top_k or 1))
    mixed_intent_query = query_has_mixed_intent_for_policy(query, policy_plugin_refs)
    if mixed_intent_query:
        exact_anchor_compacted = compact_mixed_intent_exact_anchor_records(
            list(records or []),
            query,
            top_k,
            policy_plugin_refs,
        )
        if exact_anchor_compacted:
            strong_question_supplements = [
                record
                for record in strong_question_anchor_records(list(records or []), query, policy_plugin_refs)
                if record not in exact_anchor_compacted
            ]
            if len(exact_anchor_compacted) == 1 and strong_question_supplements and not query_has_quoted_anchor_candidate(
                query
            ):
                exact_anchor_compacted = []
            else:
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
    if compaction_enabled and bool(policy_compaction.get("enabled")):
        if record_has_strong_question_anchor(limited[0], query, policy_plugin_refs):
            limited = compact_by_strong_question_anchor(limited, query, policy_plugin_refs)
        else:
            limited = filter_records_by_retrieval_policy_alignment(limited, query, policy_plugin_refs)
            limited = compact_by_strong_question_anchor(limited, query, policy_plugin_refs)
    if not limited:
        return []
    policy_compaction_enabled = bool(policy_compaction.get("enabled"))
    compaction_scores = (
        [record_rank_score(record, query, policy_plugin_refs) for record in limited]
        if policy_compaction_enabled
        else [float(record.get("score") or 0.0) for record in limited]
    )
    compacted = compact_high_confidence_items(
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


def dedupe_records(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
    record_dedupe_key: Callable[[dict[str, Any]], tuple[str, str, str]],
    record_rank_score: Callable[[dict[str, Any], str, tuple[str, ...]], float],
) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in records:
        key = record_dedupe_key(record)
        if not any(key):
            continue
        current = best_by_key.get(key)
        if current is None or record_rank_score(record, query, policy_plugin_refs) > record_rank_score(
            current,
            query,
            policy_plugin_refs,
        ):
            best_by_key[key] = record
    return list(best_by_key.values())
