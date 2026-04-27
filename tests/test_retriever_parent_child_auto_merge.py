from uuid import uuid4

from langchain_core.callbacks import CallbackManagerForRetrieverRun

from app.rag.retriever import HybridRetriever


def test_parent_child_auto_merge_replace_drops_children_and_neighbors(monkeypatch):  # noqa: ANN001
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_ENABLED", True, raising=False)
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_MODE", "replace", raising=False)
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_MIN_CHILDREN", 2, raising=False)
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_MAX_PARENTS", 20, raising=False)

    r = HybridRetriever()
    results = [
        {
            "chunk_id": "c1",
            "content": "child-1",
            "score": 0.9,
            "metadata": {"document_id": "d1", "chunk_role": "child", "parent_id": "p1"},
        },
        {
            "chunk_id": "c2",
            "content": "child-2",
            "score": 0.8,
            "metadata": {"document_id": "d1", "chunk_role": "child", "parent_id": "p1"},
        },
        {
            "chunk_id": "n1",
            "content": "neighbor",
            "score": 0.7,
            "metadata": {"document_id": "d1", "retrieval_role": "neighbor", "neighbor_of": "c1"},
        },
        {
            "chunk_id": "pchunk",
            "content": "parent",
            "score": 0.1,
            "metadata": {"document_id": "d1", "chunk_role": "parent", "parent_id": "p1"},
        },
    ]

    out = r._auto_merge_parent_child(results)
    assert len(out) == 1
    assert out[0]["chunk_id"] == "pchunk"
    assert out[0]["metadata"]["retrieval_role"] == "parent"
    assert out[0]["score"] >= 0.9 * 0.97


def test_parent_child_auto_merge_replace_keeps_single_child_group(monkeypatch):  # noqa: ANN001
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_ENABLED", True, raising=False)
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_MODE", "replace", raising=False)
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_MIN_CHILDREN", 2, raising=False)

    r = HybridRetriever()
    results = [
        {
            "chunk_id": "c1",
            "content": "child-1",
            "score": 0.9,
            "metadata": {"document_id": "d1", "chunk_role": "child", "parent_id": "p1"},
        }
    ]

    out = r._auto_merge_parent_child(results)
    assert out == results


def test_parent_child_auto_merge_append_does_not_duplicate_existing_parent(monkeypatch):  # noqa: ANN001
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_ENABLED", True, raising=False)
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_MODE", "append", raising=False)
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_MAX_PARENTS", 20, raising=False)

    r = HybridRetriever()
    results = [
        {
            "chunk_id": "pchunk",
            "content": "parent",
            "score": 0.5,
            "metadata": {"document_id": "d1", "chunk_role": "parent", "parent_id": "p1"},
        },
        {
            "chunk_id": "c1",
            "content": "child-1",
            "score": 0.9,
            "metadata": {"document_id": "d1", "chunk_role": "child", "parent_id": "p1"},
        },
    ]

    out = r._auto_merge_parent_child(results)
    assert len(out) == 2
    assert [it["chunk_id"] for it in out] == ["pchunk", "c1"]


def test_parent_child_auto_merge_replace_groups_by_hierarchy_family_key(monkeypatch):  # noqa: ANN001
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_ENABLED", True, raising=False)
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_MODE", "replace", raising=False)
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_MIN_CHILDREN", 2, raising=False)
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_MAX_PARENTS", 20, raising=False)

    r = HybridRetriever()
    results = [
        {
            "chunk_id": "c1",
            "content": "child-1",
            "score": 0.9,
            "metadata": {"document_id": "d1", "chunk_role": "child", "hierarchy_family_key": "fam1"},
        },
        {
            "chunk_id": "c2",
            "content": "child-2",
            "score": 0.8,
            "metadata": {"document_id": "d1", "chunk_role": "child", "hierarchy_family_key": "fam1"},
        },
        {
            "chunk_id": "pchunk",
            "content": "parent",
            "score": 0.1,
            "metadata": {"document_id": "d1", "chunk_role": "parent", "hierarchy_family_key": "fam1"},
        },
    ]

    out = r._auto_merge_parent_child(results)
    assert len(out) == 1
    assert out[0]["chunk_id"] == "pchunk"
    assert out[0]["metadata"]["retrieval_role"] == "parent"
    assert out[0]["score"] >= 0.9 * 0.97


def test_get_relevant_documents_small_chunk_hits_feed_parent_context(monkeypatch):  # noqa: ANN001
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_ENABLED", True, raising=False)
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_MODE", "replace", raising=False)
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_MIN_CHILDREN", 2, raising=False)
    monkeypatch.setattr("app.core.config.settings.RAG_PARENT_CHILD_AUTO_MERGE_MAX_PARENTS", 20, raising=False)

    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda self, items, stats=None, metadata_filter_override=None: list(items), raising=True)  # noqa: E501
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, items: list(items), raising=True)
    monkeypatch.setattr(HybridRetriever, "_apply_governance_policy", lambda self, items, stats=None: list(items), raising=True)
    monkeypatch.setattr(HybridRetriever, "_collapse_results_by_family", lambda self, items, stats=None: list(items), raising=True)

    document_id = str(uuid4())
    results = [
        {
            "chunk_id": "c1",
            "content": "child-1",
            "score": 0.9,
            "metadata": {"document_id": document_id, "chunk_role": "child", "parent_id": "p1"},
        },
        {
            "chunk_id": "c2",
            "content": "child-2",
            "score": 0.8,
            "metadata": {"document_id": document_id, "chunk_role": "child", "parent_id": "p1"},
        },
        {
            "chunk_id": "pchunk",
            "content": "parent-context",
            "score": 0.1,
            "metadata": {"document_id": document_id, "chunk_role": "parent", "parent_id": "p1"},
        },
    ]

    def _fake_hybrid_search(self, *, query: str, top_k: int, **_kw):  # noqa: ANN001
        assert top_k >= 2
        return list(results)

    monkeypatch.setattr(HybridRetriever, "_hybrid_search", _fake_hybrid_search, raising=True)

    retriever = HybridRetriever(k=2, tenant_id=None, dataset_id=None, document_ids=[document_id])
    docs = retriever._get_relevant_documents("q", run_manager=CallbackManagerForRetrieverRun.get_noop_manager())

    assert len(docs) == 1
    assert docs[0].id == "pchunk"
    assert docs[0].page_content == "parent-context"
    assert docs[0].metadata.get("retrieval_role") == "parent"
