from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control


class _Query:
    def filter(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
        return self

    def order_by(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
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
    def __init__(self, *, tenant_id: UUID, document_id: UUID, chunk_id: UUID, chunk_index: int, content: str):
        self.id = chunk_id
        self.chunk_index = chunk_index
        self.content = content
        self.tenant_id = tenant_id
        self.document_id = document_id
        self.page_number = None
        self.start_char = chunk_index * 10
        self.end_char = (chunk_index + 1) * 10
        self.doc_metadata = {}


@pytest.mark.asyncio
async def test_kg_extract_auto_switches_long_documents_to_heuristic(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MIN_CHARS", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MAX_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_SKIP_UNCHANGED_CHUNKS", False, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT", 0, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACTION_BACKEND", "llm", raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_LONG_DOC_BACKEND", "heuristic", raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_LONG_DOC_MIN_CHUNKS", 5, raising=False)

    import app.rag.kg.extraction.extractor as extractor_mod
    from app.rag.kg.extraction.config import ExtractConfig
    from app.rag.kg.extraction.heuristic_extractor import HeuristicExtractor
    from app.rag.kg.loading.processor import DocumentProcessor

    monkeypatch.setattr(extractor_mod, "SessionLocal", lambda: _Session(), raising=True)
    monkeypatch.setattr(extractor_mod.EventExtractor, "_writeback_document_metadata", lambda *_a, **_k: None, raising=True)

    async def _should_not_create_llm_client(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("long-document auto backend should skip LLM client creation")

    monkeypatch.setattr(extractor_mod, "create_llm_client", _should_not_create_llm_client, raising=True)

    processed_chunk_indices: list[int] = []

    async def _fake_heuristic_extract(self, sections, batch_index, **_kwargs):  # noqa: ANN001
        await yield_control()
        processed_chunk_indices.append(sections[0].chunk_index)
        return [
            {
                "title": f"heuristic-{sections[0].chunk_index}",
                "summary": "s",
                "content": "c" * 50,
                "entities": [{"name": "Alice", "type": "Person"}],
            }
        ]

    monkeypatch.setattr(HeuristicExtractor, "extract_from_sections", _fake_heuristic_extract, raising=True)

    async def _fake_generate_batch(self, texts):  # noqa: ANN001
        await yield_control()
        return [[0.1] for _ in texts]

    monkeypatch.setattr(DocumentProcessor, "generate_batch", _fake_generate_batch, raising=True)

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def upsert(self, **_kwargs):  # noqa: ANN003
            events = []
            for record in _kwargs["records"]:
                idx = int(record.chunk_id.int - 100)
                events.append(
                    SimpleNamespace(id=UUID(int=idx + 1000), chunk_id=record.chunk_id, document_id=record.document_id)
                )
            return SimpleNamespace(event_result=SimpleNamespace(events=events, entities=[]))

        def delete_event_indexes_for_chunks(self, **_kwargs):  # noqa: ANN003
            return {"events_deleted": 0, "entities_pruned": 0}

    monkeypatch.setattr(extractor_mod, "Indexer", _FakeIndexer, raising=True)

    tenant_id = UUID(int=1)
    doc_id = UUID(int=2)
    chunks = [
        _Chunk(
            tenant_id=tenant_id,
            document_id=doc_id,
            chunk_id=UUID(int=100 + i),
            chunk_index=i,
            content=f"chunk-{i} " * 20,
        )
        for i in range(10)
    ]

    cfg = ExtractConfig(chunk_ids=[c.id for c in chunks], tenant_id=tenant_id, replace_existing=False)
    extractor = extractor_mod.EventExtractor()
    events = await extractor.extract(cfg, chunks=chunks)

    assert len(events) == 10
    assert processed_chunk_indices == list(range(10))
