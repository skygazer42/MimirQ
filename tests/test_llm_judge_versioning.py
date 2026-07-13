from app.rag.evaluation.ragas import _coerce_llm_judge_payload, _llm_judge_version_hash


class _Judge:
    model_name = "judge-a"
    temperature = 0


def test_llm_judge_version_hash_tracks_model_and_rubric() -> None:
    baseline = _llm_judge_version_hash(model=_Judge())

    assert baseline == _llm_judge_version_hash(model=_Judge())
    assert baseline != _llm_judge_version_hash(model=_Judge(), generation_prompt_content="custom rubric")

    other_model = _Judge()
    other_model.model_name = "judge-b"
    assert baseline != _llm_judge_version_hash(model=other_model)


def test_llm_judge_payload_keeps_bounded_structured_details() -> None:
    out = _coerce_llm_judge_payload(
        {
            "score": 0.5,
            "reason": "one fact is missing",
            "atomic_facts": [
                {"fact": "Revenue was 100.", "verdict": "supported", "evidence_quote": "Revenue: 100"},
                "invalid",
            ],
        }
    )

    assert out["atomic_facts"] == [
        {"fact": "Revenue was 100.", "verdict": "supported", "evidence_quote": "Revenue: 100"}
    ]
