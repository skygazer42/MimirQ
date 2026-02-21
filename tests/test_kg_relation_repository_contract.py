from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID


class _FakeQuery:
    def __init__(self, *, delete_count=0, rows=None):  # noqa: ANN001
        self._delete_count = int(delete_count or 0)
        self._rows = list(rows or [])
        self.deleted = False
        self.committed = False
        self.filtered = 0
        self.ordered = False
        self.limited_to = None

    def filter(self, *_a, **_k):  # noqa: ANN001
        self.filtered += 1
        return self

    def order_by(self, *_a, **_k):  # noqa: ANN001
        self.ordered = True
        return self

    def limit(self, n):  # noqa: ANN001
        self.limited_to = int(n)
        return self

    def delete(self, **_k):  # noqa: ANN001
        self.deleted = True
        return self._delete_count

    def all(self):  # noqa: ANN001
        return list(self._rows)


class _FakeSession:
    def __init__(self, queries):  # noqa: ANN001
        self._queries = list(queries)
        self.committed = False
        self.flushed = False

    def query(self, *_a, **_k):  # noqa: ANN001
        if not self._queries:
            raise AssertionError("Unexpected session.query call")
        return self._queries.pop(0)

    def commit(self):  # noqa: D401
        self.committed = True

    def flush(self):  # noqa: D401
        self.flushed = True


def test_relation_repository_delete_relations_for_chunks_commits() -> None:
    from app.rag.kg.repository import RelationRepository

    q = _FakeQuery(delete_count=3)
    session = _FakeSession([q])
    repo = RelationRepository(session)

    deleted = repo.delete_relations_for_chunks([UUID(int=1)], tenant_id=UUID(int=99), commit=True)
    assert deleted == 3
    assert q.deleted is True
    assert session.committed is True
    assert session.flushed is False


def test_relation_repository_list_relations_for_documents_applies_limit() -> None:
    from app.rag.kg.repository import RelationRepository

    rows = [
        SimpleNamespace(id=UUID(int=1), predicate="p"),
        SimpleNamespace(id=UUID(int=2), predicate="p2"),
    ]
    q = _FakeQuery(rows=rows)
    session = _FakeSession([q])
    repo = RelationRepository(session)

    out = repo.list_relations_for_documents(tenant_id=UUID(int=99), document_ids=[UUID(int=7)], limit=10)
    assert [r.id for r in out] == [UUID(int=1), UUID(int=2)]
    assert q.ordered is True
    assert q.limited_to == 10

