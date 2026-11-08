from uuid import uuid4

import pytest

from app.rag.evaluation.synthetic import pipeline as synthetic
from app.services import chat_stream_common, document_ingestion_policy, pipeline_provenance_service


@pytest.mark.parametrize("value", [None, "", 0, False])
def test_chat_completion_projects_execution_metrics(value, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = []
    monkeypatch.setattr(chat_stream_common, "num_tokens_from_string", lambda _text: 1)
    monkeypatch.setattr(chat_stream_common, "log_metrics", captured.append)
    metrics = {"retrieval_mode": value, "vector_backend": value}
    event = chat_stream_common.build_chat_stream_done_event(
        request_id="request",
        assistant_message_id=uuid4(),
        conversation_id=uuid4(),
        content="answer",
        citations=[],
        metrics=metrics,
        retrieval_mode_default="requested",
        vector_backend_default="configured",
        structured=False,
        structured_data=None,
    )
    chat_stream_common.log_chat_stream_completion_metrics(
        request_id="request",
        conversation_id=uuid4(),
        tenant_id=uuid4(),
        metrics=metrics,
        retrieval_mode_default="requested",
        vector_backend_default="configured",
    )
    assert event["data"]["retrieval_mode"] == value
    assert event["data"]["vector_backend"] == value
    assert captured[0]["retrieval_mode"] == value
    assert captured[0]["vector_backend"] == value


@pytest.mark.parametrize("value", [0, False, [], {}])
def test_dataset_default_codec_exposes_wrong_types(value) -> None:
    with pytest.raises(AttributeError):
        document_ingestion_policy.dataset_upload_defaults({"default_parser_backend": value})


@pytest.mark.parametrize("pipeline_hash", [None, ""])
def test_pipeline_snapshot_does_not_invent_a_version_or_timestamp(pipeline_hash) -> None:
    snapshot = pipeline_provenance_service.build_pipeline_version_snapshot(
        meta={}, pipeline_hash=pipeline_hash, created_at="", build_sha="build", embedding_space_hash="space"
    )
    assert snapshot["pipeline_hash"] == pipeline_hash
    assert snapshot["created_at"] == ""


@pytest.mark.parametrize("budget,expected", [(0, 0), (1, 1), (None, 6)])
def test_synthetic_generation_honors_the_supplied_attempt_budget(budget, expected, monkeypatch) -> None:
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(synthetic, "evaluate_synthetic_sample_acceptance", lambda _sample: (False, ["rejected"]))
    result = synthetic.generate_stage2_synthetic_dataset(
        seed_rows=[{}], target_count=2, max_attempts=budget, generator_fn=generate, critic_fn=lambda sample: sample
    )
    assert len(calls) == expected
    assert result["summary"]["attempted"] == expected


@pytest.mark.parametrize("budget", [False, True, "", []])
def test_synthetic_budget_rejects_wrong_types(budget) -> None:
    with pytest.raises(TypeError):
        synthetic.generate_stage2_synthetic_dataset(seed_rows=[{}], target_count=1, max_attempts=budget)
