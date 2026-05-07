from __future__ import annotations

import gzip
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException


class _FakeQuery:
    def __init__(self, *, scalar=None, first=None, all_rows=None, delete_count: int = 0):  # noqa: ANN001
        self._scalar = scalar
        self._first = first
        self._all = all_rows
        self._delete_count = int(delete_count or 0)
        self.delete_called = False

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

    def delete(self, *_a, **_k):  # noqa: ANN001
        self.delete_called = True
        return self._delete_count


class _FakeDB:
    def __init__(self, queries):  # noqa: ANN001
        self._queries = list(queries)

    def query(self, *_a, **_k):  # noqa: ANN001
        if not self._queries:
            raise AssertionError("Unexpected db.query call")
        return self._queries.pop(0)

    def flush(self) -> None:
        return

    def commit(self) -> None:
        return

    def rollback(self) -> None:
        return


def test_get_kg_stats_no_access_returns_zero(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import get_kg_stats
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(routes_mod, "_resolve_allowed_documents", lambda **_k: [], raising=True)

    out = get_kg_stats(document_ids=None, tenant_id=UUID(int=1), account_id="u", db=object())
    assert out.events == 0
    assert out.entities == 0
    assert out.links == 0
    assert out.entity_types == []
    assert out.updated_at is None


def test_get_kg_stats_counts(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import get_kg_stats
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(routes_mod, "_resolve_allowed_documents", lambda **_k: [UUID(int=2)], raising=True)

    updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    db = _FakeDB(
        queries=[
            _FakeQuery(scalar=3),  # event_count
            _FakeQuery(scalar=12),  # link_count
            _FakeQuery(scalar=5),  # entity_count
            _FakeQuery(scalar=updated_at),  # updated_at
            _FakeQuery(all_rows=[("Person", 4), (None, 1)]),  # type_rows
        ]
    )

    out = get_kg_stats(document_ids=None, tenant_id=UUID(int=1), account_id="u", db=db)
    assert out.events == 3
    assert out.entities == 5
    assert out.links == 12
    assert out.updated_at == updated_at
    assert [t.model_dump() for t in out.entity_types] == [
        {"type": "Person", "count": 4},
        {"type": "unknown", "count": 1},
    ]


def test_get_kg_stats_accepts_dataset_scope(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import get_kg_stats

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)

    called: dict[str, object] = {}

    def _fake_resolve_allowed_documents(**kwargs):  # noqa: ANN001
        called.update(kwargs)
        return []

    monkeypatch.setattr(routes_mod, "_resolve_allowed_documents", _fake_resolve_allowed_documents, raising=True)

    out = get_kg_stats(
        document_ids=None,
        dataset_id=UUID(int=7),
        tenant_id=UUID(int=1),
        account_id="u",
        db=object(),
    )

    assert called["dataset_id"] == UUID(int=7)
    assert out.events == 0


def test_compare_kg_snapshots_passes_dataset_scope(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.rag.kg.api.routes import compare_kg_snapshots

    calls: list[dict[str, object]] = []

    def _fake_export_kg_snapshot(**kwargs):  # noqa: ANN001
        calls.append(dict(kwargs))
        return {"pipeline_hash": kwargs["pipeline_hash"]}

    monkeypatch.setattr(routes_mod, "export_kg_snapshot", _fake_export_kg_snapshot, raising=True)
    monkeypatch.setattr(
        "app.rag.kg.snapshot.diff_kg_snapshots",
        lambda a, b: {"a": a["pipeline_hash"], "b": b["pipeline_hash"]},
        raising=True,
    )

    out = compare_kg_snapshots(
        pipeline_hash_a="ph-a",
        pipeline_hash_b="ph-b",
        document_ids=None,
        dataset_id=UUID(int=7),
        tenant_id=UUID(int=1),
        account_id="u",
        db=object(),
    )

    assert out == {"a": "ph-a", "b": "ph-b"}
    assert [call["dataset_id"] for call in calls] == [UUID(int=7), UUID(int=7)]


def test_export_kg_graph_graphml(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import export_kg_graph
    from app.rag.kg.schemas import KGGraphLink, KGGraphNode, KGGraphResponse

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)

    called: dict[str, object] = {}

    def _fake_get_kg_graph(**_k):  # noqa: ANN001
        called.update(_k)
        return KGGraphResponse(
            nodes=[
                KGGraphNode(id="n1", label="Entity A", group=1, val=1, meta={"kind": "entity", "type": "Person"}),
                KGGraphNode(id="n2", label="Event 1", group=0, val=1, meta={"kind": "event", "document_id": "d"}),
            ],
            links=[
                KGGraphLink(source="n2", target="n1", label="mentions", weight=1.0, meta={"kind": "event_entity"}),
                KGGraphLink(
                    source="n1",
                    target="n1",
                    label="co",
                    weight=0.2,
                    meta={"kind": "entity_entity", "shared_events": 3},
                ),
            ],
            stats={"events": 1, "entities": 1},
        )

    monkeypatch.setattr(routes_mod, "get_kg_graph", _fake_get_kg_graph, raising=True)

    resp = export_kg_graph(
        document_ids=None,
        max_events=10,
        max_entities=10,
        max_links=10,
        include_entity_links=True,
        include_relation_links=True,
        min_shared_events=2,
        max_entity_links=1000,
        download=False,
        gzip_output=False,
        tenant_id=UUID(int=1),
        account_id="u",
        db=object(),
    )

    assert resp.media_type == "application/graphml+xml"
    assert called.get("include_relation_links") is True
    body = resp.body.decode("utf-8")
    assert "<graphml" in body
    assert 'key id="d0"' in body  # node label
    assert 'key id="e2"' in body  # edge kind
    assert "entity_entity" in body


def test_export_kg_graph_graphml_gzip(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import export_kg_graph
    from app.rag.kg.schemas import KGGraphResponse

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(
        routes_mod,
        "get_kg_graph",
        lambda **_k: KGGraphResponse(nodes=[], links=[], stats={}),
        raising=True,
    )

    resp = export_kg_graph(
        document_ids=None,
        max_events=10,
        max_entities=10,
        max_links=10,
        include_entity_links=False,
        include_relation_links=False,
        min_shared_events=2,
        max_entity_links=1000,
        download=False,
        gzip_output=True,
        tenant_id=UUID(int=1),
        account_id="u",
        db=object(),
    )

    assert resp.media_type == "application/graphml+xml"
    assert resp.headers.get("content-encoding") == "gzip"
    body = gzip.decompress(resp.body).decode("utf-8")
    assert "<graphml" in body


def test_delete_kg_for_document_uses_default_prune_setting(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import delete_kg_for_document
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_PRUNE_ORPHAN_ENTITIES", False, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(routes_mod, "filter_allowed_document_ids", lambda *_a, **_k: [UUID(int=2)], raising=True)

    called: dict[str, object] = {}

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def delete_event_indexes(self, **kwargs):  # noqa: ANN003
            called.update(kwargs)
            return {"events_deleted": 7, "entities_pruned": 2}

    import app.services.indexer as indexer_mod

    monkeypatch.setattr(indexer_mod, "Indexer", _FakeIndexer, raising=True)

    doc = SimpleNamespace(id=UUID(int=2), tenant_id=UUID(int=1), dataset_id=None)
    db = _FakeDB([_FakeQuery(first=doc)])

    out = delete_kg_for_document(
        document_id=UUID(int=2),
        prune_orphan_entities=None,
        tenant_id=UUID(int=1),
        account_id="u",
        db=db,
    )
    assert out.document_id == UUID(int=2)
    assert out.events_deleted == 7
    assert out.entities_pruned == 2
    assert called["prune_orphan_entities"] is False


def test_delete_kg_for_document_deletes_relations(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import delete_kg_for_document
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(routes_mod, "filter_allowed_document_ids", lambda *_a, **_k: [UUID(int=2)], raising=True)

    called: dict[str, object] = {}

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def delete_event_indexes(self, **kwargs):  # noqa: ANN003
            called.update(kwargs)
            return {"events_deleted": 7, "entities_pruned": 2}

    import app.services.indexer as indexer_mod

    monkeypatch.setattr(indexer_mod, "Indexer", _FakeIndexer, raising=True)

    rel_delete_query = _FakeQuery(delete_count=3)
    db = _FakeDB([rel_delete_query])

    out = delete_kg_for_document(
        document_id=UUID(int=2),
        prune_orphan_entities=False,
        tenant_id=UUID(int=1),
        account_id="u",
        db=db,
    )

    assert out.document_id == UUID(int=2)
    assert out.events_deleted == 7
    assert out.entities_pruned == 2
    assert rel_delete_query.delete_called is True


def test_get_kg_event_detail_no_access_404(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import get_kg_event_detail
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(routes_mod, "_resolve_allowed_documents", lambda **_k: [], raising=True)

    with pytest.raises(HTTPException) as exc:
        get_kg_event_detail(
            event_id=UUID(int=10),
            document_ids=None,
            tenant_id=UUID(int=1),
            account_id="u",
            db=object(),
        )
    assert exc.value.status_code == 404


def test_get_kg_event_detail_success(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import get_kg_event_detail
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(routes_mod, "_resolve_allowed_documents", lambda **_k: [UUID(int=2)], raising=True)

    ev = SimpleNamespace(
        id=UUID(int=10),
        title="t",
        summary="s",
        content="c",
        document_id=UUID(int=2),
        chunk_id=None,
        references=None,
        extra_data=None,
        created_at=None,
        updated_at=None,
    )
    ent = SimpleNamespace(
        id=UUID(int=20),
        name="Alice",
        type="Person",
        normalized_name="alice",
        description=None,
        extra_data=None,
        created_at=None,
        updated_at=None,
    )
    assoc = SimpleNamespace(
        weight=0.7,
        role="subject",
        extra_data={
            "document_id": str(UUID(int=2)),
            "chunk_id": str(UUID(int=3)),
            "start_char": 10,
            "end_char": 20,
        },
    )

    db = _FakeDB([_FakeQuery(first=ev), _FakeQuery(all_rows=[(assoc, ent)])])

    out = get_kg_event_detail(
        event_id=UUID(int=10),
        document_ids=None,
        tenant_id=UUID(int=1),
        account_id="u",
        db=db,
    )
    assert out.event.id == UUID(int=10)
    assert out.entities[0].entity.id == UUID(int=20)
    assert out.entities[0].weight == pytest.approx(0.7)
    assert out.entities[0].role == "subject"
    assert out.entities[0].extra_data.get("chunk_id") == str(UUID(int=3))
    assert out.entities[0].extra_data.get("start_char") == 10
    assert out.entities[0].extra_data.get("end_char") == 20


def test_get_kg_graph_includes_event_entity_provenance(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import get_kg_graph

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(routes_mod, "_resolve_allowed_documents", lambda **_k: [UUID(int=2)], raising=True)

    ev = SimpleNamespace(id=UUID(int=10), title="t", document_id=UUID(int=2), chunk_id=UUID(int=3))
    ent = SimpleNamespace(id=UUID(int=20), name="Alice", type="Person", normalized_name="alice")
    assoc = SimpleNamespace(
        event_id=UUID(int=10),
        role="mentions",
        weight=1.0,
        extra_data={
            "document_id": str(UUID(int=2)),
            "chunk_id": str(UUID(int=3)),
            "start_char": 10,
            "end_char": 20,
        },
    )

    db = _FakeDB(
        queries=[
            _FakeQuery(all_rows=[ev]),  # events
            _FakeQuery(all_rows=[(UUID(int=10), 1)]),  # event_degree
            _FakeQuery(all_rows=[(UUID(int=20), 1)]),  # ent_rows
            _FakeQuery(all_rows=[(assoc, ent)]),  # rows (assoc, ent)
        ]
    )

    out = get_kg_graph(
        document_ids=None,
        max_events=10,
        max_entities=10,
        max_links=10,
        include_entity_links=False,
        include_relation_links=False,
        min_shared_events=2,
        max_entity_links=1000,
        tenant_id=UUID(int=1),
        account_id="u",
        db=db,
    )

    assert len(out.links) == 1
    assert out.links[0].meta.get("kind") == "event_entity"
    assert out.links[0].meta.get("chunk_id") == str(UUID(int=3))
    assert out.links[0].meta.get("start_char") == 10
    assert out.links[0].meta.get("end_char") == 20


def test_get_kg_entity_detail_total_events_zero_404(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import get_kg_entity_detail
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(routes_mod, "_resolve_allowed_documents", lambda **_k: [UUID(int=2)], raising=True)

    ent = SimpleNamespace(
        id=UUID(int=20),
        name="Alice",
        type="Person",
        normalized_name="alice",
        description=None,
        extra_data=None,
        created_at=None,
        updated_at=None,
    )

    db = _FakeDB(
        [
            _FakeQuery(first=None),  # redirect lookup (none)
            _FakeQuery(first=ent),  # ent
            _FakeQuery(scalar=0),  # total_events
        ]
    )

    with pytest.raises(HTTPException) as exc:
        get_kg_entity_detail(
            entity_id=UUID(int=20),
            document_ids=None,
            max_events=10,
            max_neighbors=10,
            tenant_id=UUID(int=1),
            account_id="u",
            db=db,
        )
    assert exc.value.status_code == 404


def test_get_kg_entity_detail_success(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import get_kg_entity_detail
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(routes_mod, "_resolve_allowed_documents", lambda **_k: [UUID(int=2)], raising=True)

    ent = SimpleNamespace(
        id=UUID(int=20),
        name="Alice",
        type="Person",
        normalized_name="alice",
        description=None,
        extra_data=None,
        created_at=None,
        updated_at=None,
    )
    ev = SimpleNamespace(
        id=UUID(int=10),
        title="t",
        summary="s",
        content="c",
        document_id=UUID(int=2),
        chunk_id=None,
        references=None,
        extra_data=None,
        created_at=None,
        updated_at=None,
    )

    neighbor_rows = [(UUID(int=30), "Bob", "Person", 2)]
    db = _FakeDB(
        [
            _FakeQuery(first=None),  # redirect lookup (none)
            _FakeQuery(first=ent),  # ent
            _FakeQuery(scalar=3),  # total_events
            _FakeQuery(all_rows=[ev]),  # events
            _FakeQuery(all_rows=neighbor_rows),  # neighbors
        ]
    )

    out = get_kg_entity_detail(
        entity_id=UUID(int=20),
        document_ids=None,
        max_events=10,
        max_neighbors=10,
        tenant_id=UUID(int=1),
        account_id="u",
        db=db,
    )
    assert out.entity.id == UUID(int=20)
    assert [e.id for e in out.events] == [UUID(int=10)]
    assert out.neighbors[0].entity_id == UUID(int=30)
    assert out.neighbors[0].count == 2
    assert out.stats["total_events"] == 3
