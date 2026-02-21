from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest


class _Session:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def add_all(self, objs) -> None:  # noqa: ANN001
        for obj in list(objs or []):
            self.add(obj)

    def commit(self) -> None:
        return

    def flush(self) -> None:
        return

    def rollback(self) -> None:
        return

    def close(self) -> None:
        return


class _Chunk:
    def __init__(self, *, tenant_id: UUID, document_id: UUID, chunk_id: UUID, content: str, meta=None) -> None:
        self.id = chunk_id
        self.chunk_index = 0
        self.content = content
        self.tenant_id = tenant_id
        self.document_id = document_id
        self.page_number = None
        self.start_char = 10
        self.end_char = 20
        self.doc_metadata = meta or {}


@pytest.mark.asyncio
async def test_kg_extract_persists_relations_and_deletes_on_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MIN_CHARS", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MAX_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_SKIP_UNCHANGED_CHUNKS", False, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_RELATION_ENABLED", True, raising=False)

    import app.rag.kg.extraction.extractor as extractor_mod
    from app.rag.kg.extraction.config import ExtractConfig
    from app.rag.kg.extraction.processor import EventProcessor
    from app.rag.kg.extraction.relation_processor import RelationProcessor
    from app.rag.kg.loading.processor import DocumentProcessor
    from app.rag.kg.models import KgRelation

    session = _Session()
    monkeypatch.setattr(extractor_mod, "SessionLocal", lambda: session, raising=True)
    monkeypatch.setattr(extractor_mod.EventExtractor, "_writeback_document_metadata", lambda *_a, **_k: None, raising=True)

    async def _fake_create_llm_client(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        return object()

    monkeypatch.setattr(extractor_mod, "create_llm_client", _fake_create_llm_client, raising=True)

    async def _fake_extract(self, sections, batch_index):  # noqa: ANN001
        await asyncio.sleep(0)
        return [
            {
                "title": "t",
                "summary": "s",
                "content": "c" * 50,
                "entities": [
                    {"name": "Alice", "normalized_name": "alice", "type": "Person"},
                    {"name": "Bob", "normalized_name": "bob", "type": "Person"},
                ],
            }
        ]

    monkeypatch.setattr(EventProcessor, "extract_from_sections", _fake_extract, raising=True)

    async def _fake_generate_batch(self, texts):  # noqa: ANN001
        await asyncio.sleep(0)
        return [[0.1] for _ in texts]

    monkeypatch.setattr(DocumentProcessor, "generate_batch", _fake_generate_batch, raising=True)

    call_log: list[str] = []

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def upsert(self, **_kwargs):  # noqa: ANN003
            call_log.append("upsert")
            ev = SimpleNamespace(id=UUID(int=999))
            alice_ent = SimpleNamespace(id=UUID(int=11), normalized_name="alice", type="Person", name="Alice")
            bob_ent = SimpleNamespace(id=UUID(int=12), normalized_name="bob", type="Person", name="Bob")
            return SimpleNamespace(event_result=SimpleNamespace(events=[ev], entities=[alice_ent, bob_ent]))

        def delete_event_indexes_for_chunks(self, **_kwargs):  # noqa: ANN003
            call_log.append("delete_events")
            return {"events_deleted": 1, "entities_pruned": 0}

    monkeypatch.setattr(extractor_mod, "Indexer", _FakeIndexer, raising=True)

    class _FakeRelationRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def delete_relations_for_chunks(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
            call_log.append("delete_relations")
            return 0

    monkeypatch.setattr(extractor_mod, "RelationRepository", _FakeRelationRepository, raising=False)

    async def _fake_extract_relations(self, *, text: str, candidates, max_relations: int = 20):  # noqa: ANN001
        await asyncio.sleep(0)
        assert text
        assert len(list(candidates or [])) >= 2
        return [
            {
                "subject_id": "E1",
                "predicate": "works_with",
                "object_id": "E2",
                "confidence": 0.9,
                "qualifiers": None,
            }
        ]

    monkeypatch.setattr(RelationProcessor, "extract_relations", _fake_extract_relations, raising=True)

    tenant_id = UUID(int=1)
    doc_id = UUID(int=2)
    chunk_id = UUID(int=3)
    chunk = _Chunk(tenant_id=tenant_id, document_id=doc_id, chunk_id=chunk_id, content="hello world" * 10)

    cfg = ExtractConfig(chunk_ids=[chunk_id], tenant_id=tenant_id, replace_existing=True, prune_orphan_entities=False)
    extractor = extractor_mod.EventExtractor()
    await extractor.extract(cfg, chunks=[chunk])

    # Replace flow: relations should be deleted for processed chunks and re-inserted before deleting events.
    assert "upsert" in call_log
    assert "delete_relations" in call_log
    assert "delete_events" in call_log
    assert call_log.index("delete_relations") < call_log.index("delete_events")

    rels = [obj for obj in session.added if isinstance(obj, KgRelation)]
    assert len(rels) == 1
    rel = rels[0]
    assert rel.subject_entity_id == UUID(int=11)
    assert rel.object_entity_id == UUID(int=12)
    assert rel.predicate == "works_with"

