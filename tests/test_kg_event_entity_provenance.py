from __future__ import annotations

from uuid import UUID

import pytest


def test_build_event_entity_provenance_allowlists_and_coerces() -> None:
    from app.rag.kg.provenance import build_event_entity_provenance

    out = build_event_entity_provenance(
        document_id=UUID(int=1),
        chunk_id=UUID(int=2),
        references={
            "chunk_index": "3",
            "page": "5",
            "start_char": 10.2,
            "end_char": "20",
            "chunk_key": "x" * 1000,
            "content_hash": "h" * 1000,
            "content_len": "42",
            "source": "  mysrc  ",
            "unexpected": "leak",
            "nested": {"a": 1},
        },
    )

    # Required identifiers (stringified for JSON safety).
    assert out.get("document_id") == str(UUID(int=1))
    assert out.get("chunk_id") == str(UUID(int=2))

    # Coerced numeric fields.
    assert out.get("chunk_index") == 3
    assert out.get("page") == 5
    assert out.get("start_char") == 10
    assert out.get("end_char") == 20
    assert out.get("content_len") == 42

    # Bounded strings.
    assert isinstance(out.get("chunk_key"), str)
    assert len(str(out.get("chunk_key"))) <= 200
    assert isinstance(out.get("content_hash"), str)
    assert len(str(out.get("content_hash"))) <= 200
    assert out.get("source") == "mysrc"

    # Must not leak unknown keys.
    assert "unexpected" not in out
    assert "nested" not in out


def test_build_event_entity_provenance_omits_missing_fields() -> None:
    from app.rag.kg.provenance import build_event_entity_provenance

    out = build_event_entity_provenance(document_id=None, chunk_id=None, references=None)
    assert out == {}


def test_indexer_persists_event_entity_edge_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    import uuid

    import app.services.indexer as indexer_mod
    from app.types.indexing import EventEntityInput, EventInput

    class _StubMilvus:  # noqa: D401
        """No-op vector adapter."""

        def add_vectors(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
            return []

    monkeypatch.setattr(indexer_mod, "get_milvus_adapter", lambda **_k: _StubMilvus(), raising=True)

    class _FakeSession:
        def __init__(self):
            self.added = []

        def add(self, obj):  # noqa: ANN001
            self.added.append(obj)

        def commit(self):  # noqa: D401
            """No-op."""

        def flush(self):  # noqa: D401
            """No-op."""

    class _FakeEvent:
        def __init__(self, **kwargs):  # noqa: ANN003
            self.id = uuid.uuid4()
            for k, v in kwargs.items():
                setattr(self, k, v)

    class _FakeEntity:
        def __init__(self, **kwargs):  # noqa: ANN003
            self.id = uuid.uuid4()
            self.vector = None
            for k, v in kwargs.items():
                setattr(self, k, v)

    class _FakeLink:
        def __init__(self, *, event, entity, weight, role=None, extra_data=None):  # noqa: ANN001
            self.event = event
            self.entity = entity
            self.weight = weight
            self.role = role
            self.extra_data = extra_data

    monkeypatch.setattr(indexer_mod, "KgSourceEvent", _FakeEvent, raising=True)
    monkeypatch.setattr(indexer_mod, "KgEventEntity", _FakeLink, raising=True)

    def _fake_get_or_create_entity(self, **kwargs):  # noqa: ANN001, ANN003
        return _FakeEntity(**kwargs)

    monkeypatch.setattr(indexer_mod.Indexer, "_get_or_create_entity", _fake_get_or_create_entity, raising=True)

    db = _FakeSession()
    indexer = indexer_mod.Indexer(db)  # type: ignore[arg-type]

    tenant_id = UUID(int=1)
    doc_id = UUID(int=2)
    chunk_id = UUID(int=3)
    indexer.index_events(
        tenant_id=tenant_id,
        events=[
            EventInput(
                title="t",
                summary="s",
                content="c",
                document_id=doc_id,
                chunk_id=chunk_id,
                references={"start_char": 10, "end_char": 20, "page": 1, "chunk_index": 0},
                entities=[
                    EventEntityInput(
                        name="Alice",
                        normalized_name="alice",
                        type="Person",
                    )
                ],
            )
        ],
        commit=False,
        options=None,
    )

    links = [x for x in db.added if isinstance(x, _FakeLink)]
    assert len(links) == 1
    assert isinstance(links[0].extra_data, dict)
    assert links[0].extra_data.get("document_id") == str(doc_id)
    assert links[0].extra_data.get("chunk_id") == str(chunk_id)
    assert links[0].extra_data.get("start_char") == 10
    assert links[0].extra_data.get("end_char") == 20
