from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest


class _FakeQuery:
    def __init__(self, *, scalar=None, first=None, all_rows=None):  # noqa: ANN001
        self._scalar = scalar
        self._first = first
        self._all = all_rows

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def join(self, *_a, **_k):  # noqa: ANN001
        return self

    def order_by(self, *_a, **_k):  # noqa: ANN001
        return self

    def limit(self, *_a, **_k):  # noqa: ANN001
        return self

    def group_by(self, *_a, **_k):  # noqa: ANN001
        return self

    def scalar(self):  # noqa: ANN001
        return self._scalar

    def first(self):  # noqa: ANN001
        return self._first

    def all(self):  # noqa: ANN001
        return list(self._all or [])


class _FakeDB:
    def __init__(self, queries):  # noqa: ANN001
        self._queries = list(queries)

    def query(self, *_a, **_k):  # noqa: ANN001
        if not self._queries:
            raise AssertionError("Unexpected db.query call")
        return self._queries.pop(0)


def test_get_kg_graph_includes_relation_links(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import KGGraphProjectionParams, get_kg_graph

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(routes_mod, "_resolve_allowed_documents", lambda **_k: [UUID(int=2)], raising=True)

    ev = SimpleNamespace(id=UUID(int=10), title="t", document_id=UUID(int=2), chunk_id=UUID(int=3), updated_at=None)

    ent1 = SimpleNamespace(id=UUID(int=20), name="Alice", type="Person", normalized_name="alice")
    ent2 = SimpleNamespace(id=UUID(int=21), name="Bob", type="Person", normalized_name="bob")

    assoc1 = SimpleNamespace(event_id=UUID(int=10), entity_id=UUID(int=20), role="mentions", weight=1.0, extra_data={})
    assoc2 = SimpleNamespace(event_id=UUID(int=10), entity_id=UUID(int=21), role="mentions", weight=1.0, extra_data={})

    rel = SimpleNamespace(
        subject_entity_id=UUID(int=20),
        object_entity_id=UUID(int=21),
        predicate="works_with",
        confidence=0.8,
        document_id=UUID(int=2),
        chunk_id=UUID(int=3),
        event_id=UUID(int=10),
        updated_at=None,
    )

    db = _FakeDB(
        queries=[
            _FakeQuery(all_rows=[ev]),  # events
            _FakeQuery(all_rows=[(UUID(int=10), 2)]),  # event_degree
            _FakeQuery(all_rows=[(UUID(int=20), 1), (UUID(int=21), 1)]),  # ent_rows
            _FakeQuery(all_rows=[(assoc1, ent1), (assoc2, ent2)]),  # rows (assoc, ent)
            _FakeQuery(all_rows=[rel]),  # rel_rows
        ]
    )

    out = get_kg_graph(
        params=KGGraphProjectionParams(
            document_ids=None,
            max_events=10,
            max_entities=10,
            max_links=10,
            include_entity_links=False,
            include_relation_links=True,
            min_shared_events=2,
            max_entity_links=1000,
        ),
        tenant_id=UUID(int=1),
        account_id="u",
        db=db,
    )

    rel_links = [link for link in out.links if link.meta.get("kind") == "entity_relation"]
    assert len(rel_links) == 1
    assert rel_links[0].label == "works_with"
    assert rel_links[0].source == str(UUID(int=20))
    assert rel_links[0].target == str(UUID(int=21))
    assert rel_links[0].meta.get("confidence") == pytest.approx(0.8)
    assert rel_links[0].meta.get("chunk_id") == str(UUID(int=3))


def test_expand_kg_graph_includes_relation_links(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import KGGraphProjectionParams, expand_kg_graph

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(routes_mod, "_resolve_allowed_documents", lambda **_k: [UUID(int=2)], raising=True)

    ev = SimpleNamespace(id=UUID(int=10), title="t", document_id=UUID(int=2), chunk_id=UUID(int=3), updated_at=None)

    ent1 = SimpleNamespace(id=UUID(int=20), name="Alice", type="Person", normalized_name="alice")
    ent2 = SimpleNamespace(id=UUID(int=21), name="Bob", type="Person", normalized_name="bob")

    assoc1 = SimpleNamespace(event_id=UUID(int=10), entity_id=UUID(int=20), role="mentions", weight=1.0, extra_data={})
    assoc2 = SimpleNamespace(event_id=UUID(int=10), entity_id=UUID(int=21), role="mentions", weight=1.0, extra_data={})

    rel = SimpleNamespace(
        subject_entity_id=UUID(int=20),
        object_entity_id=UUID(int=21),
        predicate="works_with",
        confidence=0.8,
        document_id=UUID(int=2),
        chunk_id=UUID(int=3),
        event_id=UUID(int=10),
        updated_at=None,
    )

    db = _FakeDB(
        queries=[
            _FakeQuery(first=ev),  # center_event
            _FakeQuery(all_rows=[(UUID(int=20),), (UUID(int=21),)]),  # entity_ids_flat for center event
            _FakeQuery(all_rows=[]),  # related_event_ids
            _FakeQuery(all_rows=[ev]),  # events
            _FakeQuery(all_rows=[(UUID(int=10), 2)]),  # event_degree
            _FakeQuery(all_rows=[(UUID(int=20), 1), (UUID(int=21), 1)]),  # ent_rows
            _FakeQuery(all_rows=[(assoc1, ent1), (assoc2, ent2)]),  # rows (assoc, ent)
            _FakeQuery(all_rows=[rel]),  # rel_rows
        ]
    )

    out = expand_kg_graph(
        node_id=UUID(int=10),
        params=KGGraphProjectionParams(
            document_ids=None,
            max_events=10,
            max_entities=10,
            max_links=10,
            include_entity_links=False,
            include_relation_links=True,
            min_shared_events=2,
            max_entity_links=1000,
        ),
        tenant_id=UUID(int=1),
        account_id="u",
        db=db,
    )

    rel_links = [link for link in out.links if link.meta.get("kind") == "entity_relation"]
    assert len(rel_links) == 1
    assert rel_links[0].label == "works_with"
    assert rel_links[0].source == str(UUID(int=20))
    assert rel_links[0].target == str(UUID(int=21))
    assert rel_links[0].meta.get("confidence") == pytest.approx(0.8)
    assert rel_links[0].meta.get("chunk_id") == str(UUID(int=3))
