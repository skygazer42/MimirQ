from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control


class _Session:
    def commit(self) -> None:
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
        self.start_char = None
        self.end_char = None
        self.doc_metadata = meta or {}


@pytest.mark.asyncio
async def test_kg_extract_drops_noise_entities_before_indexing(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Regression guard: keep the KG compact and useful for RAG by dropping obvious noise entities.
    """
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MIN_CHARS", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MAX_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_SKIP_UNCHANGED_CHUNKS", False, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_RELATION_ENABLED", False, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_SKILL_ENABLED", False, raising=False)

    import app.rag.kg.extraction.extractor as extractor_mod
    from app.rag.kg.extraction.config import ExtractConfig
    from app.rag.kg.extraction.processor import EventProcessor
    from app.rag.kg.loading.processor import DocumentProcessor
    from app.types.indexing import IndexKind

    monkeypatch.setattr(extractor_mod, "SessionLocal", lambda: _Session(), raising=True)
    monkeypatch.setattr(extractor_mod.EventExtractor, "_writeback_document_metadata", lambda *_a, **_k: None, raising=True)

    async def _fake_create_llm_client(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        await yield_control()
        return object()

    monkeypatch.setattr(extractor_mod, "create_llm_client", _fake_create_llm_client, raising=True)

    async def _fake_extract(self, sections, batch_index, **_kwargs):  # noqa: ANN001
        await yield_control()
        return [
            {
                "title": "t",
                "summary": "s",
                "content": "c" * 50,
                "entities": [
                    {"name": "Alice", "type": "Person"},
                    {"name": "A", "type": "Person"},  # too-short ASCII
                    {"name": "123", "type": "Product"},  # digits-only
                    {"name": "...", "type": "Product"},  # punct-only
                ],
            }
        ]

    monkeypatch.setattr(EventProcessor, "extract_from_sections", _fake_extract, raising=True)

    async def _fake_generate_batch(self, texts):  # noqa: ANN001
        await yield_control()
        return [[0.1] for _ in texts]

    monkeypatch.setattr(DocumentProcessor, "generate_batch", _fake_generate_batch, raising=True)

    captured: dict[str, object] = {}

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def upsert(self, *, tenant_id, records, options=None, **_k):  # noqa: ANN001, ANN003
            assert tenant_id
            event_records = [r for r in records if r.kind == IndexKind.EVENT]
            assert len(event_records) == 1
            captured["entity_names"] = [e.name for e in (event_records[0].entities or [])]
            ev = SimpleNamespace(id=UUID(int=999), chunk_id=UUID(int=3))
            alice_ent = SimpleNamespace(id=UUID(int=11), normalized_name="alice", type="Person", name="Alice")
            return SimpleNamespace(event_result=SimpleNamespace(events=[ev], entities=[alice_ent]))

        def delete_event_indexes_for_chunks(self, **_kwargs):  # noqa: ANN003
            return {"events_deleted": 0, "entities_pruned": 0}

    monkeypatch.setattr(extractor_mod, "Indexer", _FakeIndexer, raising=True)

    tenant_id = UUID(int=1)
    doc_id = UUID(int=2)
    chunk_id = UUID(int=3)
    chunk = _Chunk(tenant_id=tenant_id, document_id=doc_id, chunk_id=chunk_id, content="Alice works with Bob.")

    cfg = ExtractConfig(chunk_ids=[chunk_id], tenant_id=tenant_id, replace_existing=True, prune_orphan_entities=False)
    extractor = extractor_mod.EventExtractor()
    out = await extractor.extract(cfg, chunks=[chunk])

    assert len(out) == 1
    assert captured.get("entity_names") == ["Alice"]

