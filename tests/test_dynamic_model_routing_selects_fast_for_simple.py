from app.core.config import settings
from app.rag.engine import RAGEngine


def test_dynamic_model_routing_selects_fast_for_simple_and_heavy_for_complex(monkeypatch):
    # Keep this test dependency-free: we use the built-in FakeStreamingListLLM path.
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ENABLE_DYNAMIC_MODEL_ROUTING", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MODEL_FAST", "test-fast", raising=False)
    monkeypatch.setattr(settings, "LLM_MODEL_HEAVY", "test-heavy", raising=False)
    # Make the routing decision deterministic for this test.
    monkeypatch.setattr(settings, "MODEL_COMPLEXITY_THRESHOLD", 160, raising=False)
    monkeypatch.setattr(settings, "MODEL_COMPLEXITY_HISTORY_WEIGHT", 0.0, raising=False)

    engine = RAGEngine()

    _llm, route, _reason = engine._select_llm("What is 2+2?", history=[])
    assert route == "fast"

    # Intentionally keep this below the length threshold; complexity should still route to heavy.
    complex_q = "Analyze and compare A vs B step-by-step.\n```python\nx = 1\n```"
    assert len(complex_q) < int(settings.MODEL_COMPLEXITY_THRESHOLD)

    _llm2, route2, _reason2 = engine._select_llm(complex_q, history=[])
    assert route2 == "heavy"

