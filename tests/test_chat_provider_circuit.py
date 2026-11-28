from types import SimpleNamespace

import httpx
import pytest

from app.infrastructure.config import settings
from app.services.chat import execution


def test_real_outage_is_ignored_after_enabling_mock_mode(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", False)
    monkeypatch.setattr(execution, "_MODEL_PROVIDER_CIRCUIT_KEY", "")
    monkeypatch.setattr(execution, "_MODEL_PROVIDER_UNAVAILABLE_UNTIL", 0.0)
    execution.mark_model_provider_unavailable()
    assert execution.is_model_provider_unavailable_circuit_open()
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True)
    assert not execution.is_model_provider_unavailable_circuit_open()


def test_changing_the_configured_model_invalidates_its_outage(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", False)
    monkeypatch.setattr(settings, "LLM_MODEL", "old-model")
    monkeypatch.setattr(execution, "_MODEL_PROVIDER_CIRCUIT_KEY", "")
    monkeypatch.setattr(execution, "_MODEL_PROVIDER_UNAVAILABLE_UNTIL", 0.0)
    execution.mark_model_provider_unavailable()
    assert execution.is_model_provider_unavailable_circuit_open()
    monkeypatch.setattr(settings, "LLM_MODEL", "new-model")
    assert not execution.is_model_provider_unavailable_circuit_open()


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_chat_generates_directly_without_an_extra_model_probe(monkeypatch, streaming):
    from app.api.v1.conversations import routes
    from app.rag.runtime import engine
    from app.services.chat import stream_orchestrator as streams

    requests = []

    class Client:
        def __init__(self, **_options):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_error):
            pass

        async def post(self, _url, **options):
            requests.append(options["json"])
            return SimpleNamespace(status_code=200)

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", False)
    monkeypatch.setattr(settings, "LLM_API_BASE", "https://llm.example/v1")
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(settings, "LLM_MODEL", "configured-model")
    monkeypatch.setattr(execution, "_MODEL_PROVIDER_CIRCUIT_KEY", "")
    monkeypatch.setattr(execution, "_MODEL_PROVIDER_UNAVAILABLE_UNTIL", 0.0)
    config = SimpleNamespace(answer_mode="llm", use_graph=False)
    context = SimpleNamespace(effective_rag_config=config)

    if streaming:

        async def answer(**_options):
            yield {"type": "token", "data": {"content": "actual answer"}}

        monkeypatch.setattr(streams, "_stream_langchain_events", answer)
        events = [
            event
            async for event in streams._stream_live_events(
                http_request=None,
                request_id="direct-generation",
                conversation_id=None,
                effective_rag_config=config,
                fallback_factory=None,
                execution_context=context,
                cache_feature_enabled=False,
                cache_hit=False,
                cache_skip_reason=None,
                cache_eligible=False,
                cache_key=None,
                runtime=None,
                persist_in_background=False,
                spawn_background_task=None,
                persist_options=None,
            )
        ]
        assert events == [{"type": "token", "data": {"content": "actual answer"}}]
    else:

        async def answer(**_options):
            return execution.ExecutedGraphChatOnceResult("actual answer", [], {}, None)

        monkeypatch.setattr(engine, "get_rag_engine", lambda: object())
        monkeypatch.setattr(routes, "execute_langchain_chat_once", answer)
        result = await routes._run_non_streaming_chat_generation(context=context, runtime_metrics={})
        assert result.content == "actual answer"
    assert requests == []
