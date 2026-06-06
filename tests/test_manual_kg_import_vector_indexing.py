from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.document import Document
from app.rag.kg.models import KgEntity, KgSourceEvent


def test_manual_kg_import_embeds_events_and_entities(monkeypatch):
    import app.rag.kg.manual_import as manual_import

    embedded_texts: list[str] = []
    indexed_events: list[KgSourceEvent] = []
    indexed_entities: list[KgEntity] = []

    class _FakeEmbeddings:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            embedded_texts.extend(texts)
            return [[float(index), 0.5] for index, _text in enumerate(texts, 1)]

    class _FakeIndexer:
        def __init__(self, db: object) -> None:
            self.db = db

        def _resolve_event_vector_enabled(self, options: object) -> bool:
            return True

        def _resolve_entity_vector_enabled(self, options: object) -> bool:
            return True

        def _embedding_runtime_for_document(self, *, tenant_id: UUID, document_id: UUID) -> object:
            return {"tenant_id": tenant_id, "document_id": document_id}

        def _index_event_vectors(self, events: list[KgSourceEvent]) -> list[str]:
            indexed_events.extend(events)
            return [f"event:{event.id}" for event in events]

        def _index_entity_vectors(self, entities: list[KgEntity]) -> list[str]:
            indexed_entities.extend(entities)
            return [f"entity:{entity.id}" for entity in entities]

    monkeypatch.setattr(manual_import, "Indexer", _FakeIndexer, raising=False)
    monkeypatch.setattr(
        manual_import, "create_embeddings_for_runtime", lambda _runtime: _FakeEmbeddings(), raising=False
    )

    document = Document(
        id=uuid4(),
        tenant_id=UUID(int=1),
        filename="manual.json",
        file_type="json",
        file_size=0,
        file_path="manual://test",
    )
    event = KgSourceEvent(
        id=uuid4(),
        tenant_id=UUID(int=1),
        title="Demo relation",
        summary="Record to requirement relation",
        content="Account renewal requires a signed request.",
        content_vector=None,
    )
    entity = KgEntity(
        id=uuid4(),
        tenant_id=UUID(int=1),
        name="Account renewal",
        type="DemoRecord",
        description="Demo business record",
        normalized_name="account_renewal",
        vector=None,
    )

    out = manual_import._index_manual_import_vectors(
        db=cast(Session, object()),
        tenant_id=UUID(int=1),
        document=document,
        events=[event],
        entities=[entity],
        enabled=True,
    )

    assert out["status"] == "indexed"
    assert out["events_embedded"] == 1
    assert out["entities_embedded"] == 1
    assert out["event_vectors"] == 1
    assert out["entity_vectors"] == 1
    assert embedded_texts == [
        "Demo relation\nRecord to requirement relation\nAccount renewal requires a signed request.",
        "Account renewal\nDemoRecord\nDemo business record",
    ]
    assert event.content_vector == [1.0, 0.5]
    assert entity.vector == [2.0, 0.5]
    assert indexed_events == [event]
    assert indexed_entities == [entity]


def test_manual_kg_import_vector_indexing_is_fail_open(monkeypatch):
    import app.rag.kg.manual_import as manual_import

    class _FakeIndexer:
        def __init__(self, db: object) -> None:
            self.db = db

        def _resolve_event_vector_enabled(self, options: object) -> bool:
            return True

        def _resolve_entity_vector_enabled(self, options: object) -> bool:
            return True

        def _embedding_runtime_for_document(self, *, tenant_id: UUID, document_id: UUID) -> object:
            return {"tenant_id": tenant_id, "document_id": document_id}

    def _raise_embedding_error(_runtime: object) -> object:
        raise RuntimeError("embedding backend unavailable")

    monkeypatch.setattr(manual_import, "Indexer", _FakeIndexer, raising=False)
    monkeypatch.setattr(manual_import, "create_embeddings_for_runtime", _raise_embedding_error, raising=False)

    event = KgSourceEvent(id=uuid4(), tenant_id=UUID(int=1), title="t", summary="s", content="c", content_vector=None)
    document = Document(
        id=uuid4(),
        tenant_id=UUID(int=1),
        filename="manual.json",
        file_type="json",
        file_size=0,
        file_path="manual://test",
    )

    out = manual_import._index_manual_import_vectors(
        db=cast(Session, object()),
        tenant_id=UUID(int=1),
        document=document,
        events=[event],
        entities=[],
        enabled=True,
    )

    assert out["status"] == "failed"
    assert "embedding backend unavailable" in out["error"]
    assert event.content_vector is None


def test_manual_kg_import_delete_removes_event_and_entity_vectors(monkeypatch):
    import app.rag.kg.manual_import as manual_import

    deleted_events: list[str] = []
    deleted_entities: list[str] = []

    class _FakeVector:
        def __init__(self, sink: list[str]) -> None:
            self.sink = sink

        def delete(self, ids: list[str]) -> None:
            self.sink.extend(ids)

    class _FakeIndexer:
        def __init__(self, db: object) -> None:
            self._event_vector = _FakeVector(deleted_events)
            self._entity_vector = _FakeVector(deleted_entities)

    monkeypatch.setattr(manual_import, "Indexer", _FakeIndexer, raising=False)

    event_id = uuid4()
    entity_id = uuid4()
    manual_import._delete_manual_import_vectors(
        db=cast(Session, object()), event_ids=[event_id], entity_ids=[entity_id]
    )

    assert deleted_events == [str(event_id)]
    assert deleted_entities == [str(entity_id)]
