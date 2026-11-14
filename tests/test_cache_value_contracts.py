import pytest

from app.core.config import settings
from app.rag import rerank_result_cache, retrieval_candidate_cache
from app.rag.reranker.types import RerankResult
from app.services import semantic_cache


@pytest.fixture
def candidate_parameters() -> dict:
    return {
        "tenant_id": "tenant-1",
        "account_id": "account-1",
        "dataset_id": "dataset-1",
        "pipeline_key": "pipeline-1",
        "corpus_cache_token": "corpus-1",
        "behavior_hash": "behavior-1",
        "query": "policy",
        "top_k": 5,
        "score_threshold": 0.0,
        "retrieval_mode": "hybrid",
        "metadata_filter": None,
        "document_ids": ["document-1"],
    }


@pytest.fixture
def semantic_parameters(candidate_parameters: dict) -> dict:
    return {key: value for key, value in candidate_parameters.items() if key != "pipeline_key"}


@pytest.mark.parametrize("field", ["dataset_id", "pipeline_key", "corpus_cache_token", "behavior_hash"])
def test_candidate_cache_distinguishes_empty_and_absent_scope_values(candidate_parameters: dict, field: str) -> None:
    empty = retrieval_candidate_cache.build_retrieval_candidate_cache_key(**{**candidate_parameters, field: ""})
    absent = retrieval_candidate_cache.build_retrieval_candidate_cache_key(**{**candidate_parameters, field: None})

    assert empty != absent


@pytest.mark.parametrize("field", ["dataset_id", "behavior_hash"])
def test_semantic_cache_distinguishes_empty_and_absent_scope_values(semantic_parameters: dict, field: str) -> None:
    empty, _ = semantic_cache.build_semantic_cache_scope_hash(**{**semantic_parameters, field: ""})
    absent, _ = semantic_cache.build_semantic_cache_scope_hash(**{**semantic_parameters, field: None})

    assert empty != absent


def test_rerank_cache_distinguishes_empty_and_absent_corpus_tokens() -> None:
    parameters = {
        "tenant_id": "tenant-1",
        "account_id": "account-1",
        "provider": "colbert",
        "top_n": 3,
        "query": "policy",
        "candidates_fingerprint": "candidates-1",
    }

    empty = rerank_result_cache.build_evidence_post_rerank_cache_key(**parameters, corpus_cache_token="")
    absent = rerank_result_cache.build_evidence_post_rerank_cache_key(**parameters, corpus_cache_token=None)

    assert empty != absent


@pytest.mark.parametrize("cache_kind", ["candidate", "semantic"])
@pytest.mark.parametrize(
    "field,error", [("query", AttributeError), ("top_k", TypeError), ("retrieval_mode", AttributeError)]
)
def test_cache_key_builders_expose_invalid_required_values(
    candidate_parameters: dict, semantic_parameters: dict, cache_kind: str, field: str, error: type[Exception]
) -> None:
    if cache_kind == "candidate":
        parameters = candidate_parameters
        build_key = retrieval_candidate_cache.build_retrieval_candidate_cache_key
    else:
        parameters = semantic_parameters
        build_key = semantic_cache.build_semantic_cache_scope_hash

    with pytest.raises(error):
        build_key(**{**parameters, field: None})


@pytest.mark.parametrize("provider,model", [("", ""), (None, None), ("colbert", "model-1")])
def test_rerank_cache_roundtrip_preserves_result_metadata(
    monkeypatch: pytest.MonkeyPatch, provider: str | None, model: str | None
) -> None:
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_CACHE_BACKEND", "memory")
    rerank_result_cache.clear_evidence_post_rerank_cache_for_tests()
    result = RerankResult(
        ordered_ids=["document-1"], score_map={"document-1": 0.0}, provider=provider, model_used=model
    )
    try:
        assert rerank_result_cache.set_cached_evidence_post_rerank_result("roundtrip", result)
        cached = rerank_result_cache.get_cached_evidence_post_rerank_result("roundtrip")

        assert cached is not None
        assert cached.provider == provider
        assert cached.model_used == model
        assert cached.ordered_ids == ["document-1"]
        assert cached.score_map == {"document-1": 0.0}
    finally:
        rerank_result_cache.clear_evidence_post_rerank_cache_for_tests()


@pytest.mark.parametrize("missing_field", ["provider", "model_used"])
def test_rerank_cache_exposes_missing_serialized_fields(monkeypatch: pytest.MonkeyPatch, missing_field: str) -> None:
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_CACHE_BACKEND", "memory")
    payload = {
        "ordered_ids": ["document-1"],
        "score_map": {"document-1": 0.0},
        "provider": "colbert",
        "model_used": None,
    }
    del payload[missing_field]
    rerank_result_cache.clear_evidence_post_rerank_cache_for_tests()
    try:
        assert rerank_result_cache._CACHE.set("incomplete", payload)

        with pytest.raises(KeyError, match=missing_field):
            rerank_result_cache.get_cached_evidence_post_rerank_result("incomplete")
    finally:
        rerank_result_cache.clear_evidence_post_rerank_cache_for_tests()
