from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control


class _Query:
    def filter(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
        return self

    def all(self):  # noqa: ANN201
        return []


class _Session:
    def expunge_all(self):  # noqa: D401
        """No-op."""

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


@pytest.mark.asyncio
async def test_kg_extract_raises_when_all_attempted_chunks_fail(monkeypatch):
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_CHUNK_MAX_RETRIES", 0, raising=False)
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

    async def _always_fails(self, sections, batch_index, **_kwargs):  # noqa: ANN001
        await yield_control()
        raise RuntimeError("provider down")

    monkeypatch.setattr(EventProcessor, "extract_from_sections", _always_fails, raising=True)

    tenant_id = UUID(int=1)
    doc_id = UUID(int=2)
    chunk_id = UUID(int=3)
    chunk = _Chunk(tenant_id=tenant_id, document_id=doc_id, chunk_id=chunk_id, content="hello world")

    cfg = ExtractConfig(chunk_ids=[chunk_id], tenant_id=tenant_id, replace_existing=False, prune_orphan_entities=False)
    extractor = extractor_mod.EventExtractor()

    with pytest.raises(RuntimeError, match="failed for all attempted chunks"):
        await extractor.extract(cfg, chunks=[chunk])


@pytest.mark.asyncio
async def test_heuristic_kg_extractor_builds_entity_event_from_real_text():
    from app.rag.kg.extraction.heuristic_extractor import HeuristicExtractor

    tenant_id = UUID(int=1)
    doc_id = UUID(int=2)
    chunk_id = UUID(int=3)
    chunk = _Chunk(
        tenant_id=tenant_id,
        document_id=doc_id,
        chunk_id=chunk_id,
        content=(
            "# QUIC and HTTP/3 operations\n"
            "RFC 9000 defines QUIC, a UDP-based multiplexed and secure transport. "
            "FastAPI and HTTPX are used in the MimirQ readiness workflow."
        ),
    )

    events = await HeuristicExtractor().extract_from_sections([chunk], 1, max_events=2, max_entities_per_event=8)

    assert events
    names = {entity["normalized_name"] for entity in events[0]["entities"]}
    assert "quic" in names
    assert "rfc 9000" in names
    assert "fastapi" in names


@pytest.mark.asyncio
async def test_kg_extract_releases_read_transaction_before_llm(monkeypatch):
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MAX_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_SKIP_UNCHANGED_CHUNKS", False, raising=False)

    import app.rag.kg.extraction.extractor as extractor_mod
    from app.rag.kg.extraction.config import ExtractConfig
    from app.rag.kg.extraction.processor import EventProcessor

    class _TrackingSession(_Session):
        def __init__(self):
            self.rollback_count = 0
            self.expunge_count = 0

        def expunge_all(self):
            self.expunge_count += 1

        def rollback(self):
            self.rollback_count += 1

    session = _TrackingSession()
    monkeypatch.setattr(extractor_mod, "SessionLocal", lambda: session, raising=True)

    async def _fake_create_llm_client(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        await yield_control()
        return object()

    monkeypatch.setattr(extractor_mod, "create_llm_client", _fake_create_llm_client, raising=True)

    async def _assert_released_before_llm(self, sections, batch_index, **_kwargs):  # noqa: ANN001
        await yield_control()
        assert session.expunge_count >= 1
        assert session.rollback_count >= 1
        return []

    monkeypatch.setattr(EventProcessor, "extract_from_sections", _assert_released_before_llm, raising=True)

    tenant_id = UUID(int=1)
    doc_id = UUID(int=2)
    chunk_id = UUID(int=3)
    chunk = _Chunk(tenant_id=tenant_id, document_id=doc_id, chunk_id=chunk_id, content="hello world")

    cfg = ExtractConfig(chunk_ids=[chunk_id], tenant_id=tenant_id, replace_existing=False, prune_orphan_entities=False)
    extractor = extractor_mod.EventExtractor()

    out = await extractor.extract(cfg, chunks=[chunk])

    assert out == []
