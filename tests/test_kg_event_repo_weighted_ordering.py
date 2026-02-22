from __future__ import annotations

from uuid import UUID


def test_search_events_by_entities_orders_by_weight_sum_first() -> None:
    """Event recall should prefer events with higher total edge weight (skills etc.)."""

    from app.rag.kg.repository import EventRepository

    class _FakeSession:
        def __init__(self) -> None:
            self.stmt = None

        def execute(self, stmt):  # noqa: ANN001
            self.stmt = stmt

            class _Res:
                def all(self):  # noqa: ANN201
                    return []

            return _Res()

    repo = EventRepository.__new__(EventRepository)
    repo.session = _FakeSession()

    # Valid UUIDs so the method builds a SQLAlchemy statement.
    repo.search_events_by_entities([UUID(int=1)], tenant_id=UUID(int=2))

    stmt = repo.session.stmt
    assert stmt is not None

    order_by = [str(c) for c in stmt._order_by_clauses]

    # The primary ordering should be total KgEventEntity.weight (descending), then a stable tie-break.
    assert order_by
    assert order_by[0].startswith("sum(kg_event_entities.weight)")
    assert order_by[0].endswith("DESC")
