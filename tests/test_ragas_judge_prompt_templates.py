from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.rag.evaluation.ragas import _attach_llm_judge_to_eval_items, _render_llm_judge_prompt


def test_render_llm_judge_prompt_uses_template_for_generation() -> None:
    prompt = _render_llm_judge_prompt(
        kind="generation",
        question="What happened?",
        answer="The rollout succeeded.",
        contexts=["Context A", "Context B"],
        prompt_content="Q={question}\nA={answer}\nCTX={contexts}",
        prompt_variables=["question", "answer", "contexts"],
    )

    assert "Q=What happened?" in prompt
    assert "A=The rollout succeeded." in prompt
    assert "Context A" in prompt
    assert "Context B" in prompt


def test_render_llm_judge_prompt_keeps_retrieval_prompt_compact() -> None:
    prompt = _render_llm_judge_prompt(
        kind="retrieval",
        question="What happened?",
        answer="",
        contexts=["Context A"],
        prompt_content="IGNORED {question}",
        prompt_variables=["question"],
    )

    assert "Evaluate retrieval quality ONLY" in prompt
    assert "IGNORED" not in prompt


def test_attach_llm_judge_to_eval_items_records_generation_prompt_template(monkeypatch) -> None:  # noqa: ANN001
    template_id = uuid.uuid4()

    monkeypatch.setattr(
        "app.rag.evaluation.ragas.resolve_prompt_template",
        lambda **_kwargs: SimpleNamespace(
            id=template_id,
            template_key="judge_faithfulness_ragas_zh",
            ab_experiment_key="judge-exp",
            ab_variant="B",
            content="Q={question}\nA={answer}\nCTX={contexts}",
            variables=["question", "answer", "contexts"],
        ),
    )

    class _FakeLLM:
        model_name = "judge-model"

        def invoke(self, prompt):  # noqa: ANN001
            return '{"score": 1, "reason": "ok", "evidence_quotes": ["quote"]}'

    items = [
        {
            "question": "What happened?",
            "response": "The rollout succeeded.",
            "retrieved_contexts": ["Context A"],
            "item_meta": {},
        }
    ]

    summary = _attach_llm_judge_to_eval_items(
        eval_items=items,
        llm=_FakeLLM(),
        db=object(),
        tenant_id=uuid.uuid4(),
        judge_prompt_template_key="judge_faithfulness_ragas_zh",
        judge_ab_user_key="demo",
    )

    assert summary["llm_judge_prompt_template_id"] == str(template_id)
    assert summary["llm_judge_prompt_template_key"] == "judge_faithfulness_ragas_zh"
    assert summary["llm_judge_prompt_ab_experiment_key"] == "judge-exp"
    assert summary["llm_judge_prompt_ab_variant"] == "B"
    judge_meta = items[0]["item_meta"]["llm_judge"]
    assert judge_meta["generation"]["prompt_template_key"] == "judge_faithfulness_ragas_zh"
