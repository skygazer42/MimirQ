from __future__ import annotations

from uuid import UUID


def _compile_sql(stmt) -> tuple[str, dict]:  # noqa: ANN001
    from sqlalchemy.dialects import postgresql

    compiled = stmt.compile(dialect=postgresql.dialect())
    return str(compiled), dict(compiled.params or {})


def test_event_repo_get_events_by_ids_filters_active_pipeline_when_scoped() -> None:
    """
    KG search must not surface stale events from inactive pipeline versions.

    When callers scope by document_ids (or dataset_id), repositories should constrain
    KgSourceEvent.pipeline_hash to the *active* pipeline hash persisted on the document.
    """
    from app.rag.kg.repository import EventRepository

    class _FakeRes:
        def scalars(self):  # noqa: ANN201
            return self

        def all(self):  # noqa: ANN201
            return []

    class _FakeSession:
        def __init__(self) -> None:
            self.stmt = None

        def execute(self, stmt):  # noqa: ANN001
            self.stmt = stmt
            return _FakeRes()

    repo = EventRepository.__new__(EventRepository)
    repo.session = _FakeSession()

    repo.get_events_by_ids(
        [UUID(int=1)],
        tenant_id=UUID(int=2),
        document_ids=[UUID(int=3)],
    )

    stmt = repo.session.stmt
    assert stmt is not None
    sql, params = _compile_sql(stmt)
    sql_l = sql.lower()

    assert "join documents" in sql_l
    assert "kg_source_events.pipeline_hash" in sql_l
    assert "coalesce" in sql_l
    assert "active_pipeline_hash" in {str(v) for v in params.values()}
    assert "pipeline_hash" in {str(v) for v in params.values()}


def test_event_repo_filter_entity_ids_in_documents_respects_active_pipeline() -> None:
    from app.rag.kg.repository import EventRepository

    class _FakeRes:
        def scalars(self):  # noqa: ANN201
            return self

        def all(self):  # noqa: ANN201
            return []

    class _FakeSession:
        def __init__(self) -> None:
            self.stmt = None

        def execute(self, stmt):  # noqa: ANN001
            self.stmt = stmt
            return _FakeRes()

    repo = EventRepository.__new__(EventRepository)
    repo.session = _FakeSession()

    repo.filter_entity_ids_in_documents(
        [UUID(int=10)],
        tenant_id=UUID(int=2),
        document_ids=[UUID(int=3)],
    )

    stmt = repo.session.stmt
    assert stmt is not None
    sql, params = _compile_sql(stmt)
    sql_l = sql.lower()

    assert "join documents" in sql_l
    assert "kg_source_events.pipeline_hash" in sql_l
    assert "active_pipeline_hash" in {str(v) for v in params.values()}

