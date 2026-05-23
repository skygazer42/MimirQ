from __future__ import annotations

from scripts.remote_prompt_matrix import extract_first_event_id, first_generated_question_metadata_value


def test_remote_prompt_matrix_extract_first_event_id_from_graph_nodes() -> None:
    body = {
        "nodes": [
            {"id": "entity:11111111-1111-1111-1111-111111111111"},
            {"id": "event:22222222-2222-2222-2222-222222222222"},
        ]
    }

    assert extract_first_event_id(body) == "22222222-2222-2222-2222-222222222222"


def test_remote_prompt_matrix_first_generated_question_metadata_value_reads_prompt_key() -> None:
    body = {
        "generated_questions": [
            {
                "question": "What happened?",
                "metadata": {
                    "prompt_template_key": "testset_generation_ragas_zh",
                    "prompt_ab_variant": "A",
                },
            }
        ]
    }

    assert first_generated_question_metadata_value(body, "prompt_template_key") == "testset_generation_ragas_zh"
    assert first_generated_question_metadata_value(body, "prompt_ab_variant") == "A"
