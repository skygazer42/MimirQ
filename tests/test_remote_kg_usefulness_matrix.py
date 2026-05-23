from __future__ import annotations

from scripts.remote_kg_usefulness_matrix import (
    contains_expected_text,
    diagnostics_item_for_question,
    kg_search_clue_count,
)


def test_remote_kg_usefulness_matrix_contains_expected_text_normalizes_case_and_space() -> None:
    assert contains_expected_text("Mira   Chen led the program.", "mira chen") is True
    assert contains_expected_text("Orion billing service", "orion billing") is True
    assert contains_expected_text("Alpha rollout", "beta rollout") is False


def test_remote_kg_usefulness_matrix_kg_search_clue_count_reads_wrapped_response() -> None:
    body = {"result": {"clues": [{"kind": "query_to_event"}, {"kind": "query_to_entity"}]}}
    assert kg_search_clue_count(body) == 2


def test_remote_kg_usefulness_matrix_diagnostics_item_for_question_matches_exact_question() -> None:
    body = {
        "items": [
            {
                "question": "Who led the integration program?",
                "baseline": {"metrics": {"hit_at_k": True}, "clues": [{"kind": "query_to_event"}]},
            }
        ]
    }

    item = diagnostics_item_for_question(body, "Who led the integration program?")

    assert item is not None
    assert item["baseline"]["metrics"]["hit_at_k"] is True
