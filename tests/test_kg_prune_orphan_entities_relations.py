from __future__ import annotations

from uuid import UUID


class _FakeQuery:
    def __init__(self, *, rows=None):  # noqa: ANN001
        self._rows = list(rows or [])
        self.outerjoin_calls = 0
        self.distinct_called = False

    def outerjoin(self, *_a, **_k):  # noqa: ANN001
        self.outerjoin_calls += 1
        return self

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def distinct(self):  # noqa: ANN001
        self.distinct_called = True
        return self

    def all(self):  # noqa: ANN001
        return list(self._rows)


class _FakeDeleteQuery:
    def __init__(self, db):  # noqa: ANN001
        self._db = db

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def delete(self, **_k):  # noqa: ANN001
        self._db.deleted_entities = True
        return 1


class _FakeVector:
    def __init__(self):  # noqa: D401
        self.deleted_ids = []

    def delete(self, ids):  # noqa: ANN001
        self.deleted_ids.extend(list(ids or []))


class _FakeDB:
    def __init__(self, queries):  # noqa: ANN001
        self._queries = list(queries)
        self.deleted_entities = False
        self.committed = False
        self.flushed = False

    def query(self, *_a, **_k):  # noqa: ANN001
        if not self._queries:
            raise AssertionError("Unexpected db.query call")
        q = self._queries.pop(0)
        # Allow passing a factory for the delete-query so we can bind `self`.
        if callable(q):
            return q(self)
        return q

    def commit(self):  # noqa: D401
        self.committed = True

    def flush(self):  # noqa: D401
        self.flushed = True


def test_prune_orphan_entities_considers_relations() -> None:
    """
    Regression guard: once `kg_relations` exists, pruning must consider relation edges too.

    This is intentionally a whitebox test: it asserts the query includes additional joins
    (event-entity + relation subject + relation object) and de-duplicates ids.
    """
    from app.services.indexer import Indexer

    orphan_ids = [UUID(int=1), UUID(int=2)]
    q = _FakeQuery(rows=[(orphan_ids[0],), (orphan_ids[1],)])
    db = _FakeDB([q, lambda d: _FakeDeleteQuery(d)])

    indexer = Indexer(db)
    indexer._entity_vector = _FakeVector()  # avoid touching Milvus

    pruned = indexer.prune_orphan_entities(tenant_id=UUID(int=99))
    assert pruned == 2

    # 3 joins: KgEventEntity + relation-as-subject + relation-as-object
    assert q.outerjoin_calls >= 3
    assert q.distinct_called is True
    assert db.deleted_entities is True
    assert db.committed is True
    assert set(indexer._entity_vector.deleted_ids) == {str(orphan_ids[0]), str(orphan_ids[1])}

