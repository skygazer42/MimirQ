import asyncio
from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_event_extractor_enforces_per_chunk_timeout(monkeypatch):
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_CHUNK_TIMEOUT_SEC", 0.01, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MAX_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_SKIP_UNCHANGED_CHUNKS", False, raising=False)

    import app.rag.kg.extraction.extractor as extractor_mod
    from app.rag.kg.extraction.config import ExtractConfig
    from app.rag.kg.extraction.processor import EventProcessor

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

    monkeypatch.setattr(extractor_mod, "SessionLocal", lambda: _Session(), raising=True)

    async def _fake_create_llm_client(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        return object()

    monkeypatch.setattr(extractor_mod, "create_llm_client", _fake_create_llm_client, raising=True)

    async def _slow_extract(self, sections, batch_index, **_kwargs):  # noqa: ANN001
        await asyncio.sleep(0.05)
        return []

    monkeypatch.setattr(EventProcessor, "extract_from_sections", _slow_extract, raising=True)

    tenant_id = UUID(int=1)
    doc_id = UUID(int=2)
    chunk_id = UUID(int=3)

    class _Chunk:
        def __init__(self):
            self.id = chunk_id
            self.chunk_index = 0
            self.content = "hello"
            self.tenant_id = tenant_id
            self.document_id = doc_id
            self.page_number = None
            self.start_char = None
            self.end_char = None
            self.doc_metadata = {}

    cfg = ExtractConfig(chunk_ids=[chunk_id], tenant_id=tenant_id, replace_existing=False, prune_orphan_entities=False)
    extractor = extractor_mod.EventExtractor()
    out = await extractor.extract(cfg, chunks=[_Chunk()])

    assert out == []
