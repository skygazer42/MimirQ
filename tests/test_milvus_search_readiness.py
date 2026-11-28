from types import SimpleNamespace

import pytest

from app.storage.vector.milvus import MilvusAdapter, MilvusVectorStore


@pytest.mark.parametrize("kind", ["adapter", "text"])
@pytest.mark.parametrize("collection_exists", [False, True])
def test_missing_vector_index_is_distinct_from_a_valid_empty_search(monkeypatch, kind, collection_exists):
    calls = []

    def empty_search(*args, **kwargs):
        calls.append(kwargs)
        return []

    loaded = SimpleNamespace(
        col=object() if collection_exists else None,
        similarity_search_with_score_by_vector=empty_search,
        similarity_search_with_score=empty_search,
    )
    if kind == "adapter":
        store = MilvusAdapter(collection_name="evaluation_vectors")
        query = [0.0]
    else:
        store = object.__new__(MilvusVectorStore)
        query = "known question"
    monkeypatch.setattr(store, "_require_store", lambda: loaded)

    def search():
        return store.search(query, metadata_filter={"dataset_id": "dataset-1"})

    if collection_exists:
        assert search() == []
        assert len(calls) == 1
    else:
        with pytest.raises(RuntimeError, match="Milvus collection is not initialized"):
            search()
        assert calls == []
