from types import SimpleNamespace
from uuid import uuid4

import pytest


def test_post_rerank_cache_passes_typed_scope_without_reparsing(monkeypatch):
    from app.rag.retrieval.stages import post_rerank

    tenant_id, dataset_id, document_id = uuid4(), uuid4(), uuid4()
    state = {"db": object(), "tenant_id": tenant_id, "dataset_id": dataset_id, "document_ids": [document_id]}
    calls = []

    def resolve(db, **scope):
        calls.append((db, scope))
        return "corpus-token"

    monkeypatch.setattr(post_rerank, "resolve_corpus_cache_token", resolve)
    assert post_rerank._resolve_post_rerank_corpus_cache_token(state) == "corpus-token"
    assert calls[0][1]["tenant_id"] is tenant_id
    assert calls[0][1]["dataset_id"] is dataset_id
    assert calls[0][1]["document_ids"][0] is document_id


def test_post_rerank_cache_does_not_hide_internal_token_failure(monkeypatch):
    from app.rag.retrieval.stages import post_rerank

    def fail(*_args, **_kwargs):
        raise RuntimeError("token invariant failed")

    monkeypatch.setattr(post_rerank, "resolve_corpus_cache_token", fail)
    with pytest.raises(RuntimeError, match="token invariant failed"):
        post_rerank._resolve_post_rerank_corpus_cache_token({"db": object(), "tenant_id": uuid4()})


def test_diagnostics_preserves_validated_zero_temperature_and_identity():
    from app.api.schemas.evaluation.diagnostics import KGSearchDiagnosticsRequest
    from app.rag.evaluation.benchmarks.kg_search_diagnostics import _normalize_limits

    request = KGSearchDiagnosticsRequest(dataset_id=uuid4(), llm_temperature=0.0)
    limits = _normalize_limits(request)
    assert limits.llm_temperature == 0.0
    assert limits.dataset_id is request.dataset_id


def test_enrichment_uses_uuid_from_authoritative_chunk_row(monkeypatch):
    from app.rag.retrieval.recall.retriever import HybridRetriever

    document_id = uuid4()
    seen = []
    result = object()
    monkeypatch.setattr(
        HybridRetriever,
        "_query_document_enrichment_rows",
        lambda self, _db, *, doc_ids, tenant_filter: seen.append(doc_ids) or result,
    )
    monkeypatch.setattr(HybridRetriever, "_query_first_chunk_content", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(HybridRetriever, "_populate_document_titles", lambda *_args, **_kwargs: None)
    retriever = HybridRetriever()
    assert (
        retriever._load_document_enrichment_context(
            object(),
            chunks_by_id={"chunk": SimpleNamespace(document_id=document_id)},
            chunks_by_pair={},
            tenant_filter=uuid4(),
        )
        is result
    )
    assert next(iter(seen[0])) is document_id


def test_hierarchy_fetcher_must_return_its_internal_mapping():
    from app.rag.retrieval.expansion.hierarchy import _fetch_hierarchy_docs

    with pytest.raises(TypeError):
        _fetch_hierarchy_docs(cache={}, pairs={("document", "parent")}, fetch_by_key=lambda _pairs: None)


def test_scoped_retrieval_requires_a_tenant_before_reading_a_dataset():
    from uuid import uuid4

    from app.rag.retrieval.recall.runtime_scope import RetrievalScope, resolve_runtime_scope

    scope = RetrievalScope(tenant_id=None, account_id="member", dataset_ids=(uuid4(),))
    with pytest.raises(LookupError, match="dataset-scoped embedding runtime unavailable"):
        resolve_runtime_scope(object(), scope=scope)
