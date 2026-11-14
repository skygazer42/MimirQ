from collections.abc import Callable
from typing import Any


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
