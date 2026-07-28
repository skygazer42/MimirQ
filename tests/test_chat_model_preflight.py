import time

import pytest

from app.core.config import settings
from app.services import chat_execution_runtime


@pytest.mark.asyncio
async def test_mock_mode_bypasses_provider_configuration_and_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_API_BASE", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MODEL", "", raising=False)
    monkeypatch.setattr(chat_execution_runtime, "_MODEL_PROVIDER_AVAILABLE_UNTIL", 0.0)
    monkeypatch.setattr(chat_execution_runtime, "_MODEL_PROVIDER_UNAVAILABLE_UNTIL", 0.0)
    monkeypatch.setattr(chat_execution_runtime, "_MODEL_PROVIDER_CIRCUIT_KEY", "")

    class UnexpectedAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("mock mode must not create an external HTTP client")

    monkeypatch.setattr(chat_execution_runtime.httpx, "AsyncClient", UnexpectedAsyncClient)

    assert await chat_execution_runtime.preflight_model_provider_fast() == (True, None)


@pytest.mark.asyncio
async def test_disabling_mock_mode_invalidates_mock_availability_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_API_BASE", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MODEL", "", raising=False)
    monkeypatch.setattr(chat_execution_runtime, "_MODEL_PROVIDER_AVAILABLE_UNTIL", 0.0)
    monkeypatch.setattr(chat_execution_runtime, "_MODEL_PROVIDER_UNAVAILABLE_UNTIL", 0.0)
    monkeypatch.setattr(chat_execution_runtime, "_MODEL_PROVIDER_CIRCUIT_KEY", "")

    assert await chat_execution_runtime.preflight_model_provider_fast() == (True, None)

    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", False, raising=False)
    available, reason = await chat_execution_runtime.preflight_model_provider_fast()

    assert available is False
    assert reason == "LLM_API_KEY/LLM_API_BASE/LLM_MODEL is not configured"


def test_enabling_mock_mode_invalidates_an_open_provider_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_API_BASE", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MODEL", "", raising=False)
    monkeypatch.setattr(
        chat_execution_runtime,
        "_MODEL_PROVIDER_CIRCUIT_KEY",
        chat_execution_runtime._model_provider_circuit_key(),
    )
    monkeypatch.setattr(chat_execution_runtime, "_MODEL_PROVIDER_UNAVAILABLE_UNTIL", time.monotonic() + 60.0)

    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)

    assert chat_execution_runtime.is_model_provider_unavailable_circuit_open() is False


@pytest.mark.asyncio
async def test_mock_preflight_ignores_a_previous_real_provider_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_API_BASE", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MODEL", "", raising=False)
    monkeypatch.setattr(
        chat_execution_runtime,
        "_MODEL_PROVIDER_CIRCUIT_KEY",
        chat_execution_runtime._model_provider_circuit_key(),
    )
    monkeypatch.setattr(chat_execution_runtime, "_MODEL_PROVIDER_AVAILABLE_UNTIL", 0.0)
    monkeypatch.setattr(chat_execution_runtime, "_MODEL_PROVIDER_UNAVAILABLE_UNTIL", time.monotonic() + 60.0)

    class UnexpectedAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("mock mode must not probe a previously unavailable provider")

    monkeypatch.setattr(chat_execution_runtime.httpx, "AsyncClient", UnexpectedAsyncClient)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)

    assert await chat_execution_runtime.preflight_model_provider_fast() == (True, None)
    assert chat_execution_runtime._MODEL_PROVIDER_UNAVAILABLE_UNTIL == 0.0
