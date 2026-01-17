from __future__ import annotations

from uuid import UUID


def test_find_events_by_entities_ignores_invalid_ids() -> None:
    from app.rag.kg.repository import EventRepository

    class _Session:
        def execute(self, _stmt):  # noqa: ANN001
            raise AssertionError("execute() should not be called when no valid UUIDs exist")

    repo = EventRepository.__new__(EventRepository)
    repo.session = _Session()

    out = repo.find_events_by_entities(["not-a-uuid", "also-bad"], tenant_id=UUID(int=1), limit=10)
    assert out == []


def test_find_events_by_entities_executes_when_any_valid_uuid() -> None:
    from app.rag.kg.repository import EventRepository

    calls = {"execute": 0}

    class _Result:
        def __init__(self, values):  # noqa: ANN001
            self._values = values

        def scalars(self):  # noqa: ANN001
            return self

        def all(self):  # noqa: ANN001
            return list(self._values)

    class _Session:
        def execute(self, _stmt):  # noqa: ANN001
            calls["execute"] += 1
            return _Result([])

    repo = EventRepository.__new__(EventRepository)
    repo.session = _Session()

    out = repo.find_events_by_entities(["not-a-uuid", str(UUID(int=1))], tenant_id=UUID(int=2), limit=10)
    assert out == []
    assert calls["execute"] == 1

