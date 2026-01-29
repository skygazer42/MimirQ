from __future__ import annotations

from uuid import UUID

from app.rag.kg.repository import EventRepository, _as_uuid_list


def test_as_uuid_list_dedupes_and_drops_invalid():
    u1 = UUID(int=1)
    u2 = UUID(int=2)
    assert _as_uuid_list([u1, str(u1), "not-a-uuid", u2, u2]) == [u1, u2]


def test_search_events_by_entities_invalid_ids_short_circuit():
    class _FakeSession:
        def execute(self, *_a, **_k):  # noqa: ANN001
            raise AssertionError("execute should not be called for invalid entity_ids")

    repo = EventRepository.__new__(EventRepository)
    repo.session = _FakeSession()
    assert repo.search_events_by_entities(["not-a-uuid"], tenant_id=UUID(int=3)) == []


def test_filter_entity_ids_in_documents_short_circuit():
    class _FakeSession:
        def execute(self, *_a, **_k):  # noqa: ANN001
            raise AssertionError("execute should not be called for empty inputs")

    repo = EventRepository.__new__(EventRepository)
    repo.session = _FakeSession()
    assert repo.filter_entity_ids_in_documents(["not-a-uuid"], tenant_id=UUID(int=1), document_ids=[UUID(int=2)]) == set()
    assert repo.filter_entity_ids_in_documents([UUID(int=1)], tenant_id=UUID(int=1), document_ids=[]) == set()

