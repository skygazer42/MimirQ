from __future__ import annotations

import uuid

from app.services.chat_runtime import apply_chat_runtime_metrics_context


def test_chat_runtime_metrics_context_adds_effective_prompt_template_fields() -> None:
    dataset_id = uuid.uuid4()
    prompt_template_id = uuid.uuid4()

    metrics = apply_chat_runtime_metrics_context(
        {"generation_fallback_used": True},
        dataset_id_used=dataset_id,
        effective_prompt_template_id=prompt_template_id,
        effective_prompt_template_key="rag_answer_claude_xml_zh",
        effective_prompt_ab_experiment_key="answer-exp-a",
    )

    assert metrics["dataset_id"] == str(dataset_id)
    assert metrics["prompt_template_id"] == str(prompt_template_id)
    assert metrics["prompt_template_key"] == "rag_answer_claude_xml_zh"
    assert metrics["prompt_ab_experiment_key"] == "answer-exp-a"
    assert metrics["generation_fallback_used"] is True


def test_chat_runtime_metrics_context_keeps_existing_prompt_template_metrics() -> None:
    metrics = apply_chat_runtime_metrics_context(
        {"prompt_template_key": "already-selected"},
        dataset_id_used=None,
        effective_prompt_template_key="request-selected",
    )

    assert metrics["prompt_template_key"] == "already-selected"
