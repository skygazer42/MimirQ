import json
import sys
import threading
import types
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
    import app.rag.runtime.engine as engine_module
    import app.services.chat.stream_orchestrator as orchestrator
    from app.services.runtime.retrieval_limiter import RetrievalAdmissionTimeoutError

    async def overloaded_stream(**_kwargs):  # noqa: ANN003, ANN202
        raise RetrievalAdmissionTimeoutError(2.1)
        yield  # pragma: no cover

    async def prepare_stream_runtime(**_kwargs):  # noqa: ANN003, ANN202
        return _stream_runtime(use_graph=use_graph)

    monkeypatch.setattr(
        orchestrator,
        "prepare_stream_chat_runtime",
        prepare_stream_runtime,
    )
    monkeypatch.setattr(orchestrator, "is_model_provider_unavailable_circuit_open", lambda: False)
    monkeypatch.setattr(engine_module, "get_rag_engine", lambda: object())
    monkeypatch.setattr(orchestrator, "stream_graph_chat_session_events", overloaded_stream)
    monkeypatch.setattr(orchestrator, "stream_langchain_chat_session_events", overloaded_stream)

    request_id = f"admission-timeout-{use_graph}"
    events = [
        event
        async for event in orchestrator.stream_chat_events(
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

    error_event = next(event for event in events if event["type"] == "error")
    assert error_event["request_id"] == request_id
    assert error_event["data"]["status_code"] == 503
    assert error_event["data"]["error_code"] == "SERVICE_UNAVAILABLE"
    assert error_event["data"]["retry_after_sec"] == 3


@pytest.mark.asyncio
async def test_ag_ui_consumer_close_closes_the_nested_graph_source(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.chat.stream_graph as graph
    import app.services.chat.stream_orchestrator as orchestrator
    from app.services.chat.ag_ui import encode_chat_events

    closed = threading.Event()
    graph_context = {}
    writes = []

    async def prepare_runtime(**_kwargs):
        return _stream_runtime(use_graph=True)

    def source(_state, *, context, **_kwargs):
        graph_context.update(context)
        try:
            yield "values", {"answer": "partial", "citations": []}
            assert context["cancel_event"].wait(1), "Graph source was not cancelled"
        finally:
            closed.set()

    monkeypatch.setattr(orchestrator, "prepare_stream_chat_runtime", prepare_runtime)
    monkeypatch.setattr(orchestrator, "is_model_provider_unavailable_circuit_open", lambda: False)
    workflow_module = types.ModuleType("app.rag.runtime.graph.workflow")
    workflow_module.rag_workflow = SimpleNamespace(stream=source)
    monkeypatch.setitem(sys.modules, workflow_module.__name__, workflow_module)
    monkeypatch.setattr(graph, "_build_graph_stream_state", lambda **_kwargs: {})
    monkeypatch.setattr(graph, "_maybe_attach_tag_context", lambda **_kwargs: None)
    monkeypatch.setattr(graph, "store_chat_response_cache_if_needed", lambda **kwargs: writes.append(kwargs))
    monkeypatch.setattr(graph, "dispatch_chat_stream_persistence", lambda **kwargs: writes.append(kwargs))
    assistant_message_id, conversation_id = uuid.uuid4(), uuid.uuid4()
    stream = encode_chat_events(
        orchestrator.stream_chat_events(
            http_request=SimpleNamespace(
                state=SimpleNamespace(request_id="cancel-nested-stream"),
                client=None,
                headers={},
                is_disconnected=lambda: False,
            ),
            db=SimpleNamespace(rollback=lambda: None),
            tenant_id=uuid.uuid4(),
            account_id="owner",
            request=SimpleNamespace(
                message="question",
                enable_summary_memory=False,
                enable_structured_memory=False,
                structured_output=False,
                structured_preset=None,
            ),
            conversation_id=conversation_id,
            scope_dataset_id=None,
            allowed_doc_ids=[],
            long_term_messages=[],
            assistant_message_id=assistant_message_id,
            tenant_qps_meta=None,
            quota_meta=None,
            spawn_background_task=lambda _task: None,
        ),
        thread_id=str(conversation_id),
        run_id="cancelled-run",
        assistant_message_id=str(assistant_message_id),
        request_id="cancel-nested-stream",
    )
    try:
        async for chunk in stream:
            if chunk.startswith("data: ") and json.loads(chunk[6:]).get("delta") == "partial":
                break
    finally:
        await stream.aclose()
    assert closed.is_set()
    assert graph_context["cancel_event"].is_set()
    assert writes == []
