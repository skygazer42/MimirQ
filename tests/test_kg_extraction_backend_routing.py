from __future__ import annotations


def test_backend_router_defaults_to_llm(monkeypatch):
    from app.core import config as config_mod
    from app.rag.kg.extraction.backend_router import resolve_extraction_backend

    llm_processor = object()
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACTION_BACKEND", "llm", raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_GLINER_ENABLED", False, raising=False)

    selected = resolve_extraction_backend(llm_processor=llm_processor, requested_backend=None)

    assert selected.backend == "llm"
    assert selected.processor is llm_processor
    assert selected.fallback_reason is None


def test_backend_router_gliner_disabled_falls_back_to_llm(monkeypatch):
    from app.core import config as config_mod
    from app.rag.kg.extraction.backend_router import resolve_extraction_backend

    llm_processor = object()
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACTION_BACKEND", "gliner", raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_GLINER_ENABLED", False, raising=False)

    selected = resolve_extraction_backend(llm_processor=llm_processor, requested_backend=None)

    assert selected.backend == "llm"
    assert selected.processor is llm_processor
    assert selected.fallback_reason == "gliner_disabled"


def test_backend_router_gliner_missing_dependency_falls_back_to_llm(monkeypatch):
    from app.core import config as config_mod
    from app.rag.kg.extraction.backend_router import resolve_extraction_backend

    llm_processor = object()
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACTION_BACKEND", "gliner", raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_GLINER_ENABLED", True, raising=False)

    import app.rag.kg.extraction.gliner_extractor as gliner_mod

    monkeypatch.setattr(gliner_mod.GLiNERExtractor, "is_available", staticmethod(lambda: False), raising=True)

    selected = resolve_extraction_backend(llm_processor=llm_processor, requested_backend=None)

    assert selected.backend == "llm"
    assert selected.processor is llm_processor
    assert selected.fallback_reason == "gliner_dependency_missing"


def test_backend_router_hybrid_selects_hybrid_processor_when_available(monkeypatch):
    from app.core import config as config_mod
    from app.rag.kg.extraction.backend_router import resolve_extraction_backend

    llm_processor = object()
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACTION_BACKEND", "hybrid", raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_GLINER_ENABLED", True, raising=False)

    import app.rag.kg.extraction.gliner_extractor as gliner_mod

    monkeypatch.setattr(gliner_mod.GLiNERExtractor, "is_available", staticmethod(lambda: True), raising=True)

    selected = resolve_extraction_backend(llm_processor=llm_processor, requested_backend=None)

    assert selected.backend == "hybrid"
    assert selected.processor.__class__.__name__ == "HybridExtractor"
    assert selected.fallback_reason is None
