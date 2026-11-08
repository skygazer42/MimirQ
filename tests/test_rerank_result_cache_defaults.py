def test_reranker_model_none_is_normalized_to_empty_signature_value(monkeypatch):
    from app.rag import rerank_result_cache

    monkeypatch.setattr(rerank_result_cache.settings, "RERANKER_MODEL", None)
    signature = rerank_result_cache._provider_version_signature("bge")
    assert signature["reranker_model"] == ""
