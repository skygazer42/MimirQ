from __future__ import annotations


def test_resolve_language_aware_model_id_prefers_language_specific_override(monkeypatch) -> None:  # noqa: ANN001
    import app.rag.embedding.factory as factory

    monkeypatch.setattr(factory.settings, "EMBEDDING_LANGUAGE_ROUTING_ENABLED", True, raising=False)
    monkeypatch.setattr(factory.settings, "EMBEDDING_MODEL", "openai/text-embedding-3-small", raising=False)
    monkeypatch.setattr(factory.settings, "EMBEDDING_MODEL_ZH", "local/BAAI/bge-large-zh-v1.5", raising=False)
    monkeypatch.setattr(factory.settings, "EMBEDDING_MODEL_EN", "openai/text-embedding-3-small", raising=False)
    monkeypatch.setattr(factory.settings, "EMBEDDING_MODEL_MIXED", "siliconflow/BAAI/bge-m3", raising=False)

    assert factory.resolve_language_aware_model_id(language="zh") == "local/BAAI/bge-large-zh-v1.5"
    assert factory.resolve_language_aware_model_id(language="mixed") == "siliconflow/BAAI/bge-m3"
    assert factory.resolve_language_aware_model_id(language="en") == "openai/text-embedding-3-small"


def test_resolve_language_aware_model_id_can_detect_language_from_text(monkeypatch) -> None:  # noqa: ANN001
    import app.rag.embedding.factory as factory

    monkeypatch.setattr(factory.settings, "EMBEDDING_LANGUAGE_ROUTING_ENABLED", True, raising=False)
    monkeypatch.setattr(factory.settings, "EMBEDDING_MODEL", "openai/text-embedding-3-small", raising=False)
    monkeypatch.setattr(factory.settings, "EMBEDDING_MODEL_ZH", "local/BAAI/bge-large-zh-v1.5", raising=False)

    out = factory.resolve_language_aware_model_id(text="这是一个中文测试。", current_model_id="openai/text-embedding-3-small")
    assert out == "local/BAAI/bge-large-zh-v1.5"


def test_resolve_language_aware_model_id_falls_back_when_mapping_is_unsupported(monkeypatch) -> None:  # noqa: ANN001
    import app.rag.embedding.factory as factory

    monkeypatch.setattr(factory.settings, "EMBEDDING_LANGUAGE_ROUTING_ENABLED", True, raising=False)
    monkeypatch.setattr(factory.settings, "EMBEDDING_MODEL", "openai/text-embedding-3-small", raising=False)
    monkeypatch.setattr(factory.settings, "EMBEDDING_MODEL_ZH", "unsupported/model", raising=False)

    out = factory.resolve_language_aware_model_id(language="zh")
    assert out == "openai/text-embedding-3-small"
