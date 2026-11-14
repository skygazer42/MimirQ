from uuid import uuid4

from app.services.semantic_cache import _semantic_cache_result_matches


def test_missing_cache_account_identity_does_not_match_an_empty_account():
    tenant_id = uuid4()
    result = {
        "id": "cached-answer",
        "score": 0.9,
        "metadata": {
            "tenant_id": str(tenant_id),
            "account_id": None,
            "scope_hash": "scope",
            "corpus_cache_token": "corpus",
            "embedding_space_hash": "embedding",
        },
    }
    assert _semantic_cache_result_matches(
        result, tenant_id=tenant_id, account_id="", scope_hash="scope",
        corpus_cache_token="corpus", embedding_space_hash="embedding",
    ) is None
