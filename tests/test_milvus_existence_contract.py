from types import SimpleNamespace

import pytest

from app.storage.vector.milvus import MilvusVectorStore


def _store(collection):
    store = object.__new__(MilvusVectorStore)
    store._store = SimpleNamespace(col=collection, _primary_field="id")
    store._require_store = lambda: store._store
    return store


def test_existence_check_exposes_the_original_query_failure() -> None:
    class Collection:
        def query(self, **_kwargs):
            raise ConnectionError("query unavailable")

    with pytest.raises(ConnectionError, match="query unavailable"):
        _store(Collection()).fetch_existing_ids(["vector"])


@pytest.mark.parametrize("rows", [None, {}, False, [None], [{}], [{"id": None}], [{"id": False}], [{"id": []}]])
def test_existence_check_rejects_invalid_query_results(rows) -> None:
    collection = SimpleNamespace(query=lambda **_kwargs: rows)
    with pytest.raises((TypeError, ValueError, KeyError)):
        _store(collection).fetch_existing_ids(["vector"])


def test_existence_check_does_not_report_partial_success_after_a_batch_failure() -> None:
    class Collection:
        def __init__(self):
            self.calls = 0

        def query(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return [{"id": "first"}]
            raise ConnectionError("second batch unavailable")

    with pytest.raises(ConnectionError, match="second batch unavailable"):
        _store(Collection()).fetch_existing_ids(["first", "second"], max_ids_per_query=1)


def test_existence_check_preserves_an_actual_empty_result() -> None:
    assert _store(SimpleNamespace(query=lambda **_kwargs: [])).fetch_existing_ids(["vector"]) == set()


def test_existence_check_recognizes_an_absent_collection() -> None:
    assert _store(None).fetch_existing_ids(["vector"]) == set()


def test_existence_check_requires_query_capability() -> None:
    with pytest.raises(AttributeError):
        _store(SimpleNamespace()).fetch_existing_ids(["vector"])
