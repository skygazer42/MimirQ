import pytest


def test_structured_output_builds_request_llm_with_deterministic_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag import engine as eng

    captured: list[dict] = []

    class _FakeLLM:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name
            self.model = model_name

    def _fake_build_llm(self, _chat_cls, model_name: str):  # noqa: ANN001
        return _FakeLLM(model_name)

    def _fake_build_chat_model_from_config(*, model_config, http_client, http_async_client, streaming):  # noqa: ANN001
        captured.append(
            {
                "model_config": dict(model_config or {}),
                "http_client": http_client,
                "http_async_client": http_async_client,
                "streaming": streaming,
            }
        )
        return _FakeLLM(str((model_config or {}).get("model") or "override"))

    monkeypatch.setattr(eng.RAGEngine, "_build_llm", _fake_build_llm, raising=True)
    monkeypatch.setattr(eng, "build_chat_model_from_config", _fake_build_chat_model_from_config, raising=True)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_DYNAMIC_MODEL_ROUTING", False, raising=False)
    monkeypatch.setattr(settings, "LLM_MODEL", "demo-default", raising=False)
    monkeypatch.setattr(settings, "LLM_TEMPERATURE", 0.7, raising=False)
    monkeypatch.setattr(settings, "LLM_STRUCTURED_TEMPERATURE", 0.0, raising=False)

    engine = eng.RAGEngine()
    original = _FakeLLM("demo-default")

    overridden, meta = engine._maybe_override_llm_for_request(
        llm=original,
        model_route="default",
        structured_output=True,
    )

    assert overridden is not original
    assert captured[0]["model_config"]["model"] == "demo-default"
    assert captured[0]["model_config"]["temperature"] == pytest.approx(0.0)
    assert captured[0]["streaming"] is True
    assert meta["structured_temperature_override_applied"] is True
    assert meta["structured_temperature"] == pytest.approx(0.0)
    assert meta["base_temperature"] == pytest.approx(0.7)


def test_structured_output_reuses_selected_llm_when_temperatures_already_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag import engine as eng

    class _FakeLLM:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name
            self.model = model_name

    monkeypatch.setattr(eng.RAGEngine, "_build_llm", lambda self, _chat_cls, model_name: _FakeLLM(model_name), raising=True)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_DYNAMIC_MODEL_ROUTING", False, raising=False)
    monkeypatch.setattr(settings, "LLM_MODEL", "demo-default", raising=False)
    monkeypatch.setattr(settings, "LLM_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(settings, "LLM_STRUCTURED_TEMPERATURE", 0.0, raising=False)

    engine = eng.RAGEngine()
    original = _FakeLLM("demo-default")

    reused, meta = engine._maybe_override_llm_for_request(
        llm=original,
        model_route="default",
        structured_output=True,
    )

    assert reused is original
    assert meta["structured_temperature_override_applied"] is False
