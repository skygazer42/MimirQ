from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control


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
    def __init__(self, *, tenant_id: UUID, document_id: UUID, chunk_id: UUID, content: str, meta=None):
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
async def test_kg_extract_skips_short_chunks(monkeypatch):
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MIN_CHARS", 10, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MAX_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_SKIP_UNCHANGED_CHUNKS", False, raising=False)

    import app.rag.kg.extraction.extractor as extractor_mod
    from app.rag.kg.extraction.config import ExtractConfig
    from app.rag.kg.extraction.processor import EventProcessor

    monkeypatch.setattr(extractor_mod, "SessionLocal", lambda: _Session(), raising=True)

    async def _fake_create_llm_client(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        await yield_control()
        return object()

    monkeypatch.setattr(extractor_mod, "create_llm_client", _fake_create_llm_client, raising=True)

    async def _should_not_be_called(self, sections, batch_index, **_kwargs):  # noqa: ANN001
        await yield_control()
        raise AssertionError("LLM should not be called for short chunks")

    monkeypatch.setattr(EventProcessor, "extract_from_sections", _should_not_be_called, raising=True)

    tenant_id = UUID(int=1)
    doc_id = UUID(int=2)
    chunk_id = UUID(int=3)
    chunk = _Chunk(tenant_id=tenant_id, document_id=doc_id, chunk_id=chunk_id, content="hi")

    cfg = ExtractConfig(chunk_ids=[chunk_id], tenant_id=tenant_id, replace_existing=False, prune_orphan_entities=False)
    extractor = extractor_mod.EventExtractor()
    out = await extractor.extract(cfg, chunks=[chunk])
    assert out == []


@pytest.mark.asyncio
async def test_kg_extract_retries_transient_failures(monkeypatch):
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_CHUNK_MAX_RETRIES", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_CHUNK_RETRY_BACKOFF_SEC", 0.0, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MAX_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_SKIP_UNCHANGED_CHUNKS", False, raising=False)

    import app.rag.kg.extraction.extractor as extractor_mod
    from app.rag.kg.extraction.config import ExtractConfig
    from app.rag.kg.extraction.processor import EventProcessor

    monkeypatch.setattr(extractor_mod, "SessionLocal", lambda: _Session(), raising=True)

    async def _fake_create_llm_client(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        await yield_control()
        return object()

    monkeypatch.setattr(extractor_mod, "create_llm_client", _fake_create_llm_client, raising=True)

    calls = {"count": 0}

    async def _flaky_extract(self, sections, batch_index, **_kwargs):  # noqa: ANN001
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("transient")
        await yield_control()
        return []

    monkeypatch.setattr(EventProcessor, "extract_from_sections", _flaky_extract, raising=True)

    tenant_id = UUID(int=1)
    doc_id = UUID(int=2)
    chunk_id = UUID(int=3)
    chunk = _Chunk(tenant_id=tenant_id, document_id=doc_id, chunk_id=chunk_id, content="hello world")

    cfg = ExtractConfig(chunk_ids=[chunk_id], tenant_id=tenant_id, replace_existing=False, prune_orphan_entities=False)
    extractor = extractor_mod.EventExtractor()
    out = await extractor.extract(cfg, chunks=[chunk])

    assert out == []
    assert calls["count"] == 2
