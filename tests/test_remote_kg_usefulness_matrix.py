from __future__ import annotations

from scripts.remote_kg_usefulness_matrix import (
    answer_match_summary,
    chat_expectation_summary,
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


def test_remote_kg_usefulness_matrix_answer_match_summary_supports_expected_terms_threshold() -> None:
    summary = answer_match_summary(
        {
            "expected_terms": ["Blue Harbor", "Mira Chen", "Orion billing service"],
            "min_expected_terms": 2,
        },
        "Mira Chen led the Blue Harbor integration program.",
    )

    assert summary["matched_terms"] == ["Blue Harbor", "Mira Chen"]
    assert summary["matched_term_count"] == 2
    assert summary["matches_expectation"] is True


def test_remote_kg_usefulness_matrix_answer_match_summary_falls_back_to_expected_answer() -> None:
    summary = answer_match_summary(
        {"expected_answer": "Mira Chen"},
        "After the acquisition, Mira Chen led the integration program.",
    )

    assert summary["matched_term_count"] == 0
    assert summary["matches_expectation"] is True


def test_remote_kg_usefulness_matrix_chat_expectation_summary_can_use_citation_gate_without_term_match() -> None:
    summary = chat_expectation_summary(
        {
            "expected_terms": ["Project Atlas", "Blue Harbor", "Mira Chen"],
            "min_expected_terms": 3,
            "require_expected_match": False,
            "min_citations": 3,
        },
        "This answer stays extractive and generic.",
        citation_count=3,
    )

    assert summary["matches_expectation"] is False
    assert summary["passes_gate"] is True
