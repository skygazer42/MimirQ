from typing import Any

from app.services.dify_integration.record_helpers import (
    compact_fast_record_content,
    compact_mixed_intent_exact_anchor_records,
    compact_records_for_response,
)


def test_compact_fast_record_content_preserves_metadata_precedence_and_line_order() -> None:
    def structured_fields(text: str) -> dict[str, str]:
        if text == "body":
            return {"问题": "Q", "答案": "Long answer", "材料": "ID"}
        if text == "地点：窗口":
            return {"地点": "窗口"}
        return {}

    result = compact_fast_record_content(
        " body ",
        query="where",
        policy_plugin_refs=("policy",),
        metadata={"region": "north"},
        max_chars=200,
        structured_label_values_from_content=structured_fields,
        response_hints_for_metadata=lambda metadata, refs: {"enabled": bool(metadata and refs)},
        metadata_answer_highlights=lambda metadata, hints, query, refs: ["地点：窗口"],
        requested_fast_response_labels=lambda query, fields, refs: ("问题", "答案", "材料"),
        fast_response_always_labels_for_policy_refs=lambda refs: ("问题", "答案"),
        requested_label_prefixes_for_policy_refs=lambda refs: ("命中字段",),
        clamp_hint_value=lambda value, limit: value[:limit],
        compact_fast_answer_value=lambda value, query, limit: "Short",
    )

    assert result == "命中字段：材料\n问题：Q\n答案：Short\n材料：ID"


def test_compact_fast_record_content_falls_back_to_metadata_then_body() -> None:
    common: dict[str, Any] = {
        "query": "q",
        "policy_plugin_refs": (),
        "max_chars": 8,
        "structured_label_values_from_content": lambda text: {},
        "response_hints_for_metadata": lambda metadata, refs: {},
        "requested_fast_response_labels": lambda query, fields, refs: (),
        "fast_response_always_labels_for_policy_refs": lambda refs: (),
        "requested_label_prefixes_for_policy_refs": lambda refs: (),
        "clamp_hint_value": lambda value, limit: value[:limit],
        "compact_fast_answer_value": lambda value, query, limit: value,
    }

    assert (
        compact_fast_record_content(
            "body text",
            metadata={"x": 1},
            metadata_answer_highlights=lambda metadata, hints, query, refs: ["metadata text"],
            **common,
        )
        == "metadata"
    )
    assert (
        compact_fast_record_content(
            "body text",
            metadata=None,
            metadata_answer_highlights=lambda metadata, hints, query, refs: [],
            **common,
        )
        == "body tex"
    )


def test_compact_mixed_intent_exact_anchor_records_preserves_decision_order() -> None:
    records = [{"id": "first"}, {"id": "second"}]
    common: dict[str, Any] = {
        "query": 'compare "anchor"',
        "top_k": 1,
        "policy_plugin_refs": (),
        "requested_policy_slot_specs_for_query": lambda query, refs: (("slot", "label"),),
        "query_has_quoted_anchor_candidate": lambda query: True,
        "record_exact_query_anchor_terms": lambda record, query, refs: ("anchor",),
        "record_content_is_answerful": lambda record, refs: record["id"] == "second",
        "records_have_confident_metadata_anchor": lambda rows, query, refs: False,
        "record_has_any_requested_slot_field": lambda record, slots: False,
        "compact_exact_anchor_answer_record": lambda rows, query, refs: [rows[-1]],
    }

    composite = {"id": "composite"}
    assert compact_mixed_intent_exact_anchor_records(
        records,
        composite_record_for_exact_anchor_slots=lambda rows, query, slots, refs: composite,
        **common,
    ) == [composite]

    assert compact_mixed_intent_exact_anchor_records(
        records,
        composite_record_for_exact_anchor_slots=lambda rows, query, slots, refs: None,
        **common,
    ) == [records[1]]


def test_compact_records_for_response_preserves_mixed_intent_supplement_guard() -> None:
    records = [{"id": "anchor", "score": 0.9}, {"id": "supplement", "score": 0.8}]

    result = compact_records_for_response(
        records,
        query="compare",
        top_k=2,
        query_has_mixed_intent_for_policy=lambda query, refs: True,
        compact_mixed_intent_exact_anchor_records=lambda rows, query, top_k, refs: [rows[0]],
        strong_question_anchor_records=lambda rows, query, refs: [rows[1]],
        query_has_quoted_anchor_candidate=lambda query: False,
        compact_exact_anchor_answer_record=lambda rows, query, refs: [],
        compaction_enabled=True,
        response_compaction_for_records=lambda rows, refs: {"enabled": True},
        record_has_strong_question_anchor=lambda record, query, refs: False,
        compact_by_strong_question_anchor=lambda rows, query, refs: rows,
        filter_records_by_retrieval_policy_alignment=lambda rows, query, refs: rows,
        record_rank_score=lambda record, query, refs: float(record["score"]),
        compact_high_confidence_items=lambda rows, scores, top_k, enabled, top, floor, minimum: rows,
        default_min_top_score=0.7,
        default_relative_score_floor=0.65,
        default_min_items=1,
    )

    assert result == records


def test_compact_records_for_response_preserves_policy_filter_and_score_contract() -> None:
    records = [{"id": "first", "score": 0.4}, {"id": "second", "score": 0.8}]
    observed: dict[str, Any] = {}

    def compact_high(
        rows: list[dict[str, Any]],
        scores: list[float],
        top_k: int,
        enabled: bool,
        top_score: float,
        floor: float,
        minimum: int,
    ) -> list[dict[str, Any]]:
        observed.update(
            rows=rows,
            scores=scores,
            top_k=top_k,
            enabled=enabled,
            top_score=top_score,
            floor=floor,
            minimum=minimum,
        )
        return rows[:1]

    result = compact_records_for_response(
        records,
        query="normal",
        top_k=2,
        query_has_mixed_intent_for_policy=lambda query, refs: False,
        compact_mixed_intent_exact_anchor_records=lambda rows, query, top_k, refs: [],
        strong_question_anchor_records=lambda rows, query, refs: [],
        query_has_quoted_anchor_candidate=lambda query: False,
        compact_exact_anchor_answer_record=lambda rows, query, refs: [],
        compaction_enabled=True,
        response_compaction_for_records=lambda rows, refs: {
            "enabled": True,
            "min_top_score": 0.9,
            "relative_score_floor": 0.5,
            "min_records": 2,
        },
        record_has_strong_question_anchor=lambda record, query, refs: False,
        compact_by_strong_question_anchor=lambda rows, query, refs: rows,
        filter_records_by_retrieval_policy_alignment=lambda rows, query, refs: list(reversed(rows)),
        record_rank_score=lambda record, query, refs: float(record["score"]) + 1.0,
        compact_high_confidence_items=compact_high,
        default_min_top_score=0.7,
        default_relative_score_floor=0.65,
        default_min_items=1,
    )

    assert result == [records[1]]
    assert observed == {
        "rows": [records[1], records[0]],
        "scores": [1.8, 1.4],
        "top_k": 2,
        "enabled": True,
        "top_score": 0.9,
        "floor": 0.5,
        "minimum": 2,
    }
