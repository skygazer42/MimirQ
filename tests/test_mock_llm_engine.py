from __future__ import annotations


def test_llm_mock_enabled_builds_fake_streaming_llm(monkeypatch) -> None:
    from app.core.config import settings
    import app.rag.engine as engine_mod

    # Ensure we build a fresh engine using the patched settings.
    engine_mod.reset_rag_engine()

    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "E2E_MOCK_OK", raising=False)

    rag = engine_mod.get_rag_engine()
    assert rag.models["default"].__class__.__name__ == "FakeStreamingListLLM"

