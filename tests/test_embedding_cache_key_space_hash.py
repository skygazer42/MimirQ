

def test_embed_cache_key_includes_embedding_space_hash(monkeypatch):  # noqa: ANN001
    """
    Cache keys must change when the embedding "space" changes (e.g. base_url swap),
    otherwise Redis can serve vectors from an incompatible model endpoint.
    """
    import app.rag.embedding.adapter as adapter_mod

    monkeypatch.setattr(adapter_mod.settings, "EMBEDDING_CACHE_PREFIX", "emb", raising=False)
    monkeypatch.setattr(adapter_mod.settings, "EMBEDDING_PROVIDER", "openai_compatible", raising=False)
    monkeypatch.setattr(adapter_mod.settings, "EMBEDDING_MODEL", "text-embedding-3-small", raising=False)

    monkeypatch.setattr(adapter_mod.settings, "EMBEDDING_API_BASE", "http://a.example/v1", raising=False)
    key_a = adapter_mod._embed_cache_key("hello")

    monkeypatch.setattr(adapter_mod.settings, "EMBEDDING_API_BASE", "http://b.example/v1", raising=False)
    key_b = adapter_mod._embed_cache_key("hello")

    assert key_a != key_b
