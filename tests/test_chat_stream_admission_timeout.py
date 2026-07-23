import json
import uuid
from types import SimpleNamespace

import pytest


def _stream_runtime(*, use_graph: bool) -> SimpleNamespace:
    return SimpleNamespace(
        effective_rag_config=SimpleNamespace(
            answer_mode="llm",
            retrieval_mode="hybrid",
            use_graph=use_graph,
        ),
        dataset_id_used=None,
        dataset_rag_defaults_applied_fields=[],
        effective_prompt_template_id=None,
        effective_prompt_template_key=None,
        effective_prompt_ab_experiment_key=None,
        dataset_prompt_defaults_applied_fields=[],
        dataset_rag_config_template_defaults_applied_fields=[],
        rag_config_template_meta={},
        history_for_llm=[],
        cache_feature_enabled=False,
        cache_key=None,
        cache_skip_reason=None,
        cache_eligible=False,
        cache_hit=False,
        full_response="",
        citations_data=[],
        metrics_data={},
        structured_data=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("use_graph", [True, False], ids=["graph", "langchain"])
async def test_stream_chat_reports_retryable_admission_timeout(
    monkeypatch: pytest.MonkeyPatch,
    use_graph: bool,
) -> None:
    import app.rag.engine as engine_module
    import app.services.chat_stream_orchestrator as orchestrator
    from app.services.rag_runtime_limiter import RetrievalAdmissionTimeoutError

    async def provider_available() -> tuple[bool, None]:
        return True, None

    async def overloaded_stream(**_kwargs):  # noqa: ANN003, ANN202
        raise RetrievalAdmissionTimeoutError(2.1)
        yield  # pragma: no cover

    monkeypatch.setattr(
        orchestrator,
        "prepare_stream_chat_runtime",
        lambda **_kwargs: _stream_runtime(use_graph=use_graph),
    )
    monkeypatch.setattr(orchestrator, "is_model_provider_unavailable_circuit_open", lambda: False)
    monkeypatch.setattr(orchestrator, "preflight_model_provider_fast", provider_available)
    monkeypatch.setattr(engine_module, "get_rag_engine", lambda: object())
    monkeypatch.setattr(orchestrator, "stream_graph_chat_session_events", overloaded_stream)
    monkeypatch.setattr(orchestrator, "stream_langchain_chat_session_events", overloaded_stream)

    request_id = f"admission-timeout-{use_graph}"
    chunks = [
        chunk
        async for chunk in orchestrator.stream_chat_sse_events(
            http_request=SimpleNamespace(
                state=SimpleNamespace(request_id=request_id),
                client=SimpleNamespace(host="127.0.0.1"),
                headers={},
                is_disconnected=lambda: False,
            ),
            db=SimpleNamespace(),
            tenant_id=uuid.uuid4(),
            account_id="member-1",
            request=SimpleNamespace(
                message="question",
                enable_summary_memory=False,
                enable_structured_memory=False,
                structured_output=False,
                structured_preset=None,
            ),
            conversation_id=None,
            scope_dataset_id=None,
            allowed_doc_ids=[],
            long_term_messages=[],
            assistant_message_id=uuid.uuid4(),
            tenant_qps_meta=None,
            quota_meta=None,
            spawn_background_task=lambda _task: None,
        )
    ]

    events = [json.loads(chunk.removeprefix("data: ")) for chunk in chunks if chunk.startswith("data: ")]
    error_event = next(event for event in events if event["type"] == "error")
    assert error_event["request_id"] == request_id
    assert error_event["data"]["status_code"] == 503
    assert error_event["data"]["error_code"] == "SERVICE_UNAVAILABLE"
    assert error_event["data"]["retry_after_sec"] == 3
