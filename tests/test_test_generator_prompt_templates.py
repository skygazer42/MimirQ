from __future__ import annotations

from app.rag.evaluation.test_generator import _build_testgen_prompt_inputs, _normalize_testgen_result_rows


def test_build_testgen_prompt_inputs_supports_builtin_testset_variables() -> None:
    payload = _build_testgen_prompt_inputs(
        chunk_text="Chunk body for prompt selection.",
        num_questions=3,
        normalized_types=["factual", "multi_hop"],
        existing_questions=["Q1", "Q2"],
        prompt_variables=["document_chunk", "n", "existing_questions"],
    )

    assert payload == {
        "document_chunk": "Chunk body for prompt selection.",
        "n": 3,
        "existing_questions": "Q1\nQ2",
    }


def test_build_testgen_prompt_inputs_preserves_legacy_prompt_shape() -> None:
    payload = _build_testgen_prompt_inputs(
        chunk_text="Legacy chunk body.",
        num_questions=2,
        normalized_types=["comparison", "conditional"],
        existing_questions=[],
        prompt_variables=["text", "num_questions", "question_types"],
    )

    assert payload == {
        "text": "Legacy chunk body.",
        "num_questions": 2,
        "question_types": "comparison, conditional",
    }


def test_normalize_testgen_result_rows_accepts_builtin_qa_pairs_shape() -> None:
    rows = _normalize_testgen_result_rows(
        {
            "qa_pairs": [
                {
                    "question": "What color is the flag?",
                    "ground_truth": "The flag is blue.",
                    "difficulty": "reasoning",
                    "evidence_quotes": ["blue flag"],
                    "expected_chunks": ["alpha"],
                }
            ]
        }
    )

    assert rows == [
        {
            "question": "What color is the flag?",
            "expected_answer": "The flag is blue.",
            "question_type": "reasoning",
            "expected_refusal": False,
            "evidence_quotes": ["blue flag"],
            "expected_chunks": ["alpha"],
        }
    ]
