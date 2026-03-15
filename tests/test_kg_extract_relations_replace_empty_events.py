from __future__ import annotations

import asyncio
from uuid import UUID

import pytest


class _Query:
    def filter(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
        return self

    def all(self):  # noqa: ANN201
        return []


class _Session:
    def commit(self):  # noqa: D401
        """No-op."""

    def rollback(self):  # noqa: D401
        """No-op."""

    def close(self):  # noqa: D401
        """No-op."""

    def query(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
        return _Query()


class _Chunk:
    def __init__(self, *, tenant_id: UUID, document_id: UUID, chunk_id: UUID, content: str, meta=None) -> None:
        self.id = chunk_id
        self.chunk_index = 0
        self.content = content
        self.tenant_id = tenant_id
        self.document_id = document_id
        self.page_number = None
        self.start_char = None
        self.end_char = None
        self.doc_metadata = meta or {}


@pytest.mark.asyncio
async def test_kg_extract_replace_existing_deletes_relations_when_no_events_extracted(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MIN_CHARS", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MAX_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_SKIP_UNCHANGED_CHUNKS", False, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_RELATION_ENABLED", True, raising=False)

    import app.rag.kg.extraction.extractor as extractor_mod
    from app.rag.kg.extraction.config import ExtractConfig
    from app.rag.kg.extraction.processor import EventProcessor

    monkeypatch.setattr(extractor_mod, "SessionLocal", lambda: _Session(), raising=True)
    monkeypatch.setattr(extractor_mod.EventExtractor, "_writeback_document_metadata", lambda *_a, **_k: None, raising=True)

    async def _fake_create_llm_client(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        await asyncio.sleep(0)  # Sonar S7503
        return object()

    monkeypatch.setattr(extractor_mod, "create_llm_client", _fake_create_llm_client, raising=True)

    async def _extract_no_events(self, sections, batch_index, **_kwargs):  # noqa: ANN001
        await asyncio.sleep(0)
        return []

    monkeypatch.setattr(EventProcessor, "extract_from_sections", _extract_no_events, raising=True)

    call_log: list[str] = []

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def delete_event_indexes_for_chunks(self, **_kwargs):  # noqa: ANN003
            call_log.append("delete_events")
            return {"events_deleted": 1, "entities_pruned": 0}

    class _FakeRelationRepository:
        def __init__(self, _db):  # noqa: ANN001
            return

        def delete_relations_for_chunks(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
            call_log.append("delete_relations")
            return 0

    monkeypatch.setattr(extractor_mod, "Indexer", _FakeIndexer, raising=True)
    monkeypatch.setattr(extractor_mod, "RelationRepository", _FakeRelationRepository, raising=False)

    tenant_id = UUID(int=1)
    doc_id = UUID(int=2)
    chunk_id = UUID(int=3)
    chunk = _Chunk(tenant_id=tenant_id, document_id=doc_id, chunk_id=chunk_id, content="hello world" * 10)

    cfg = ExtractConfig(chunk_ids=[chunk_id], tenant_id=tenant_id, replace_existing=True, prune_orphan_entities=True)
    extractor = extractor_mod.EventExtractor()
    out = await extractor.extract(cfg, chunks=[chunk])

    assert out == []
    assert call_log == ["delete_relations", "delete_events"]
