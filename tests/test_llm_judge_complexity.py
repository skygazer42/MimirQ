from types import SimpleNamespace
from uuid import uuid4

from app.rag.evaluation import llm_judge as judge_mod
from app.rag.evaluation.llm_judge import (
    attach_llm_judge_to_eval_items,
    coerce_llm_judge_payload,
)


def test_coerce_llm_judge_payload_clamps_score_quotes_and_detail_fields() -> None:
    payload = coerce_llm_judge_payload(
        {
            "score": "1.7",
            "explanation": "reason",
            "quotes": ["one", "one", "two", "three", "four"],
            "chunk_judgments": [
                {
                    "rank": 1,
                    "is_relevant": True,
                    "evidence_quote": "matched",
                    "ignored": "value",
                },
                "invalid",
            ],
        }
    )

    assert payload == {
        "score": 1.0,
        "reason": "reason",
        "evidence_quotes": ["one", "two", "three"],
        "chunk_judgments": [
            {"rank": 1, "is_relevant": True, "evidence_quote": "matched"},
        ],
    }


def test_coerce_llm_judge_payload_handles_invalid_score_and_string_quote() -> None:
    payload = coerce_llm_judge_payload(
        {
            "score": "not-a-number",
            "evidence": "direct quote",
        }
    )

    assert payload == {
        "score": None,
        "reason": "",
        "evidence_quotes": ["direct quote"],
    }


def test_attach_llm_judge_merges_item_meta_and_prompt_selection(monkeypatch) -> None:
    template_id = uuid4()
    tenant_id = uuid4()
    template = SimpleNamespace(
        id=template_id,
        content="Question: {question}\nAnswer: {answer}\nContexts: {contexts}",
        variables=["question", "answer", "contexts"],
        version=4,
        template_key="judge-v4",
        ab_experiment_key="judge-exp",
        ab_variant="b",
    )
    monkeypatch.setattr(judge_mod, "resolve_prompt_template", lambda **_kwargs: template)

    calls: list[dict] = []

    def fake_run_llm_judge(**kwargs):
        calls.append(kwargs)
        score = 0.8 if kwargs["kind"] == "retrieval" else 0.6
        return {"score": score, "reason": kwargs["kind"]}

    monkeypatch.setattr(judge_mod, "run_llm_judge", fake_run_llm_judge)
    items = [
        {
            "question": "What changed?",
            "response": "The policy changed.",
            "retrieved_contexts": ["context one", "context two"],
            "item_meta": {"existing": True},
        },
        {"question": "", "response": "ignored", "retrieved_contexts": []},
        "invalid",
    ]
    llm = SimpleNamespace(model_name="judge-model", temperature=0)

    summary = attach_llm_judge_to_eval_items(
        eval_items=items,
        llm=llm,
        db=object(),
        tenant_id=tenant_id,
        judge_prompt_template_id=template_id,
        self_consistency_n=2,
        position_bias_enabled=False,
    )

    assert [call["kind"] for call in calls] == ["retrieval", "generation"]
    assert calls[1]["prompt_content"] == template.content
    assert items[0]["item_meta"]["existing"] is True
    attached = items[0]["item_meta"]["llm_judge"]
    assert attached["overall_score"] == 0.7
    assert attached["version_hash"] == summary["llm_judge_version_hash"]
    assert summary["llm_judge_items"] == 1
    assert summary["llm_judge_retrieval_avg"] == 0.8
    assert summary["llm_judge_generation_avg"] == 0.6
    assert summary["llm_judge_overall_avg"] == 0.7
    assert summary["llm_judge_prompt_template_id"] == str(template_id)
    assert summary["llm_judge_prompt_template_key"] == "judge-v4"
    assert summary["llm_judge_prompt_ab_variant"] == "b"
