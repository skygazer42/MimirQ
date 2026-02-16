from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document


@pytest.mark.asyncio
async def test_ingest_retry_resumes_without_reparsing(monkeypatch, tmp_path):  # noqa: ANN001
    """
    When ingest fails after parsing, a retry should resume from the last checkpoint
    without re-running the expensive parsing stage.
    """

    import app.parsing.processors.processor as processor_mod
    from app.core.config import settings

    # Enable parsed-content persistence so we have a durable checkpoint to resume from.
    monkeypatch.setattr(settings, "PERSIST_PARSED_CONTENT", True, raising=False)
    monkeypatch.setattr(settings, "PERSIST_PARSED_CONTENT_MAX_CHARS", 200_000, raising=False)

    # Keep the flow lightweight for unit test.
    monkeypatch.setattr(settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "GOVERNANCE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "CHUNK_DEDUP_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "CHUNK_MIN_CHARS", 0, raising=False)
    monkeypatch.setattr(settings, "MAX_CHUNKS_PER_DOCUMENT", 0, raising=False)
    monkeypatch.setattr(settings, "NEAR_DEDUP_ENABLED", False, raising=False)

    svc = processor_mod.DocumentProcessorService()
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()

    file_path = tmp_path / "demo.txt"
    file_path.write_text("hello world", encoding="utf-8")

    class _DummyDoc:
        def __init__(self) -> None:
            self.id = document_id
            self.tenant_id = tenant_id
            self.dataset_id = None
            self.filename = "demo.txt"
            self.file_type = "txt"
            self.file_path = str(file_path)
            self.status = "pending"
            self.processing_progress = 0
            self.current_stage = None
            self.error_message = None
            self.total_characters = 0
            self.chunk_count = 0
            self.doc_metadata = {
                "file_sha256": "a" * 64,
                "pipeline_hash": "ph1",
                "active_pipeline_hash": "ph1",
                "active_pipeline_ready": False,
            }

    dummy_doc = _DummyDoc()

    class _DummyQuery:
        def __init__(self, model, db):  # noqa: ANN001
            self._model = model
            self._db = db

        def populate_existing(self):  # noqa: ANN201
            return self

        def filter(self, *_a, **_k):  # noqa: ANN001, ANN201
            return self

        def first(self):  # noqa: ANN201
            if self._model is processor_mod.DBDocument:
                return dummy_doc
            if self._model is processor_mod.DocumentParsedContent:
                return self._db.parsed_content
            return None

    class _DummyDB:
        def __init__(self) -> None:
            self.parsed_content = None

        def query(self, model):  # noqa: ANN001, ANN201
            return _DummyQuery(model, self)

        def add(self, obj) -> None:  # noqa: ANN001
            if isinstance(obj, processor_mod.DocumentParsedContent):
                self.parsed_content = obj

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

    db = _DummyDB()

    # Capture parse calls to ensure retry does not re-run parsing.
    parse_calls = {"count": 0}

    async def _fake_parse_run(self, **_kwargs):  # noqa: ANN001, ANN202
        parse_calls["count"] += 1
        return processor_mod.ParseResult(
            resolved_backend="basic",
            resolved_chunk_strategy="langchain_recursive",
            documents=[Document(page_content="Hello from parser", metadata={"page": 1})],
        )

    monkeypatch.setattr(processor_mod.ParsingStage, "run", _fake_parse_run, raising=True)

    def _fake_chunking_run(self, **_kwargs):  # noqa: ANN001, ANN202
        return processor_mod.ChunkingResult(chunks=[Document(page_content="chunk-1", metadata={"page": 1})])

    monkeypatch.setattr(processor_mod.ChunkingStage, "run", _fake_chunking_run, raising=True)

    def _fake_chunk_asset_run(self, *, chunks, **_kwargs):  # noqa: ANN001, ANN202
        return processor_mod.ChunkAssetResult(chunks=list(chunks or []), img_ids=[])

    monkeypatch.setattr(processor_mod.ChunkAssetStage, "run", _fake_chunk_asset_run, raising=True)

    # Prevent cleanup code from attempting external connections (Milvus).
    monkeypatch.setattr(processor_mod.Indexer, "delete_chunk_indexes", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        processor_mod.Indexer,
        "delete_chunk_indexes_for_doc_pipeline_key",
        lambda *_a, **_k: None,
        raising=True,
    )

    index_calls = {"count": 0}

    def _index_stage_run(self, **_kwargs):  # noqa: ANN001, ANN202
        index_calls["count"] += 1
        if index_calls["count"] == 1:
            raise RuntimeError("embedding_failed")
        return processor_mod.IndexResult(chunk_ids=[], total_characters=0, db_chunks=[])

    monkeypatch.setattr(processor_mod.IndexStage, "run", _index_stage_run, raising=True)

    # First attempt: parsing runs and we checkpoint parsed content, then indexing fails.
    with pytest.raises(RuntimeError, match="embedding_failed"):
        await svc.process_document(
            file_path=file_path,
            document_id=document_id,
            tenant_id=tenant_id,
            parser_backend="basic",
            chunk_strategy="langchain_recursive",
            db=db,
        )

    assert parse_calls["count"] == 1
    assert db.parsed_content is not None

    # Second attempt: should resume from checkpoint and not call parsing again.
    result = await svc.process_document(
        file_path=file_path,
        document_id=document_id,
        tenant_id=tenant_id,
        parser_backend="basic",
        chunk_strategy="langchain_recursive",
        db=db,
    )
    assert parse_calls["count"] == 1
    assert result.get("status") == "success"

