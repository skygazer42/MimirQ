from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.mark.parametrize("runtime_failure", [False, True])
def test_manual_kg_uses_the_owned_runtime_and_event_vector_operations(
    runtime_failure: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models.knowledge_graph.entities import KgEntity, KgSourceEvent
    from app.rag.ingestion.indexing import indexer as events
    from app.rag.kg import manual_import
    from app.services.datasets.embedding_config import DatasetEmbeddingRuntimeConfig

    tenant_id, document_id = uuid4(), uuid4()
    document = SimpleNamespace(id=document_id)
    event = KgSourceEvent(
        id=uuid4(),
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_id=uuid4(),
        title="event",
        summary="summary",
        content="content",
        pipeline_hash="pipeline-1",
        references={"chunk_index": 0},
        content_vector=None,
    )
    entity = KgEntity(
        id=uuid4(),
        tenant_id=tenant_id,
        name="entity",
        normalized_name="entity",
        type="concept",
        description="description",
    )
    runtime = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="local-test",
        api_base="",
        api_key="",
        embedding_space_hash="space",
        collection_name="documents",
        dataset_scoped=False,
    )
    writes, deletes = [], []
    db = SimpleNamespace(flush=lambda: None)

    def resolve(metadata):
        assert metadata is None
        if runtime_failure:
            raise events.DatasetScopedEmbeddingRuntimeResolutionError("runtime lookup failed")
        return runtime

    class Embeddings:
        def embed_documents(self, texts):
            return [[1.0] for _ in texts]

    class Adapter:
        def __init__(self, collection_name):
            self.collection_name = collection_name

        def add_vectors(self, items, *, embeddings):
            assert len(items) == len(embeddings)
            writes.append((self.collection_name, items))
            return [item["id"] for item in items]

        def delete(self, ids):
            deletes.append((self.collection_name, ids))

    monkeypatch.setattr(events.settings, "EVENT_VECTOR_ENABLED", True)
    monkeypatch.setattr(events.settings, "ENTITY_VECTOR_ENABLED", True)
    monkeypatch.setattr(manual_import, "resolve_dataset_embedding_runtime", resolve)
    monkeypatch.setattr(
        manual_import,
        "create_embeddings_for_runtime",
        lambda current: Embeddings() if current is runtime else pytest.fail("wrong runtime"),
    )
    monkeypatch.setattr(events, "resolve_collection_name", lambda name: name)
    monkeypatch.setattr(events, "get_milvus_adapter", lambda *, collection_name, vector_field: Adapter(collection_name))
    result = manual_import._index_manual_import_vectors(
        db=db,
        tenant_id=tenant_id,
        document=document,
        events=[event],
        entities=[entity],
        enabled=True,
    )
    if runtime_failure:
        assert result["status"] == "failed"
        assert result["error"] == "runtime lookup failed"
        assert writes == []
        return
    assert result["status"] == "indexed"
    assert result["events_embedded"] == result["entities_embedded"] == 1
    assert result["event_vectors"] == result["entity_vectors"] == 1
    assert [collection for collection, _ in writes] == ["kg_events", "kg_entities"]
    assert writes[0][1][0]["metadata"]["doc_pipeline_key"] == f"{document_id}:pipeline-1"
    assert all(item["metadata"]["tenant_id"] == str(tenant_id) for _, items in writes for item in items)
    manual_import._delete_manual_import_vectors(db=db, event_ids=[event.id], entity_ids=[entity.id])
    assert deletes == [("kg_events", [str(event.id)]), ("kg_entities", [str(entity.id)])]
