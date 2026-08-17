from app.rag.evaluation.llm_judge import coerce_llm_judge_payload, llm_judge_version_hash, run_llm_judge


class _Judge:
    model_name = "judge-a"
    temperature = 0

    def __init__(self, scores: list[float] | None = None) -> None:
        self._scores = list(scores or [0.5])
        self._calls = 0

    def invoke(self, _prompt: str):  # noqa: ANN001
        score = self._scores[min(self._calls, len(self._scores) - 1)]
        self._calls += 1
        return (
            '{"score": '
            + str(score)
            + ', "reason": "scored", "evidence_quotes": ["quote"], '
            + '"atomic_facts": [{"fact": "Revenue was 100.", '
            + '"verdict": "supported", "evidence_quote": "Revenue: 100"}]}'
        )


def test_llm_judge_version_hash_tracks_model_and_rubric() -> None:
    baseline = llm_judge_version_hash(model=_Judge())

    assert baseline == llm_judge_version_hash(model=_Judge())
    assert baseline != llm_judge_version_hash(model=_Judge(), generation_prompt_content="custom rubric")

    other_model = _Judge()
    other_model.model_name = "judge-b"
    assert baseline != llm_judge_version_hash(model=other_model)


def test_llm_judge_payload_keeps_bounded_structured_details() -> None:
    out = coerce_llm_judge_payload(
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


def test_llm_judge_uses_self_consistency_median_and_position_bias() -> None:
    result = run_llm_judge(
        llm=_Judge(scores=[0.2, 0.8, 0.6, 0.4]),
        kind="generation",
        question="q",
        answer="a",
        contexts=["ctx-1", "ctx-2"],
        self_consistency_n=3,
        position_bias_enabled=True,
    )

    assert result["score_forward_median"] == 0.6
    assert result["position_bias"]["reversed_score"] == 0.4
    assert result["position_bias"]["delta"] == 0.2
    assert result["score"] == 0.5
    assert result["score_basis"] == "self_consistency_median_position_debiased"
