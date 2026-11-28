def test_reranker_model_signature_preserves_none(monkeypatch):
    import json

    from app.rag.retrieval.cache import reranking as rerank_result_cache

    monkeypatch.setattr(rerank_result_cache.settings, "RERANKER_MODEL", None)
    monkeypatch.setattr(rerank_result_cache, "current_embedding_space_hash", lambda: "fixture-space")
    hashed_values = []
    monkeypatch.setattr(
        rerank_result_cache, "stable_hash", lambda value, **kwargs: hashed_values.append(value) or "fixture-hash"
    )
    rerank_result_cache.build_evidence_post_rerank_cache_key(
        tenant_id=None,
        account_id=None,
        provider="api",
        top_n=1,
        query="query",
        candidates_fingerprint="candidates",
    )
    signature = json.loads(hashed_values[-1])
    assert signature["provider_version"]["reranker_model"] is None
