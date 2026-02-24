import pytest


def test_kg_pipeline_enforces_gate_even_when_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.pipeline as pipeline_mod
    from app.core import config as config_mod

    created = {"count": 0}

    class _FakeEngine:
        def __init__(self) -> None:
            created["count"] += 1

    monkeypatch.setattr(pipeline_mod, "KGEngine", _FakeEngine, raising=True)

    # Start clean (avoid cross-test leakage).
    pipeline_mod.reset_kg_engine()

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    engine1 = pipeline_mod._load_engine()
    engine2 = pipeline_mod._load_engine()
    assert engine1 is engine2
    assert created["count"] == 1

    # Disabling KG must invalidate the cached engine and hard-fail.
    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", False, raising=False)
    with pytest.raises(RuntimeError, match="KG plugin is disabled"):
        pipeline_mod._load_engine()

    assert pipeline_mod._engine is None


def test_reset_kg_engine_drops_cached_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.pipeline as pipeline_mod
    from app.core import config as config_mod

    created = {"count": 0}

    class _FakeEngine:
        def __init__(self) -> None:
            created["count"] += 1

    monkeypatch.setattr(pipeline_mod, "KGEngine", _FakeEngine, raising=True)

    pipeline_mod.reset_kg_engine()
    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)

    engine1 = pipeline_mod._load_engine()
    assert created["count"] == 1

    pipeline_mod.reset_kg_engine()
    engine2 = pipeline_mod._load_engine()
    assert engine2 is not engine1
    assert created["count"] == 2

