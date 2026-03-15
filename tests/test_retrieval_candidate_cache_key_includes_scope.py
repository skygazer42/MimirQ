import importlib


def _load_module():  # noqa: ANN202
    try:
        return importlib.import_module("app.rag.retrieval_candidate_cache")
    except ModuleNotFoundError:
        return None


def test_retrieval_candidate_cache_key_builder_exists() -> None:
    mod = _load_module()
    assert mod is not None, "Expected app.rag.retrieval_candidate_cache to exist"
    assert hasattr(mod, "build_retrieval_candidate_cache_key")


def test_retrieval_candidate_cache_key_changes_with_scope() -> None:
    mod = _load_module()
    if mod is None or not hasattr(mod, "build_retrieval_candidate_cache_key"):
        # Existence is asserted above; keep this test readable.
        return

    build = mod.build_retrieval_candidate_cache_key

    base = {
        "tenant_id": "t1",
        "account_id": "acct-1",
        "dataset_id": "ds-1",
        "pipeline_key": "pipe-a",
        "corpus_cache_token": "corp-a",
        "query": "hello world",
        "top_k": 10,
        "score_threshold": 0.5,
        "retrieval_mode": "hybrid",
        "metadata_filter": {"source": "kb"},
        "document_ids": [],
    }

    k0 = build(**base)
    assert isinstance(k0, str) and k0

    assert build(**{**base, "tenant_id": "t2"}) != k0
    assert build(**{**base, "account_id": "acct-2"}) != k0
    assert build(**{**base, "dataset_id": "ds-2"}) != k0
    assert build(**{**base, "pipeline_key": "pipe-b"}) != k0
    assert build(**{**base, "corpus_cache_token": "corp-b"}) != k0
