from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document

from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_ingest_progress_moves_through_expected_stages(monkeypatch, tmp_path):  # noqa: ANN001
    """
    Progress reporting should be meaningful and ordered.

    We unit-test the orchestrator by stubbing heavy stages and capturing calls to
    `_update_status`, rather than running real parsing/vector IO.
    """

    import app.parsing.processors.processor as processor_mod

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
            self.doc_metadata = {}

    dummy_doc = _DummyDoc()

    class _DummyQuery:
        def __init__(self, model):  # noqa: ANN001
            self._model = model

        def populate_existing(self):  # noqa: ANN201
            return self

        def filter(self, *_a, **_k):  # noqa: ANN001, ANN201
            return self

        def first(self):  # noqa: ANN201
            if self._model is processor_mod.DBDocument:
                return dummy_doc
            return None

    class _DummyDB:
        def query(self, model):  # noqa: ANN001, ANN201
            return _DummyQuery(model)

        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def add_all(self, _objs) -> None:  # noqa: ANN001
            return None

        def flush(self) -> None:
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

    db = _DummyDB()

    progress_events: list[tuple[str, int]] = []

    async def _fake_update_status(  # noqa: ANN001, ANN202
        self,
        db,
        tenant_id,
        document_id,
        status,
        progress,
        stage,
        **kwargs,
    ):
        await yield_control()
        progress_events.append((str(stage), int(progress)))
        return None

    monkeypatch.setattr(processor_mod.DocumentProcessorService, "_update_status", _fake_update_status, raising=True)

    async def _fake_parse_run(self, **_kwargs):  # noqa: ANN001, ANN202
        await yield_control()
        return processor_mod.ParseResult(
            resolved_backend="basic",
            resolved_chunk_strategy="langchain_recursive",
            documents=[Document(page_content="hello", metadata={})],
        )

    monkeypatch.setattr(processor_mod.ParsingStage, "run", _fake_parse_run, raising=True)

    def _fake_chunking_run(self, **_kwargs):  # noqa: ANN001, ANN202
        return processor_mod.ChunkingResult(chunks=[Document(page_content="chunk-1", metadata={})])

    monkeypatch.setattr(processor_mod.ChunkingStage, "run", _fake_chunking_run, raising=True)

    def _fake_chunk_dedup_run(self, *, chunks, **_kwargs):  # noqa: ANN001, ANN202
        return processor_mod.ChunkDedupResult(chunks=list(chunks or []), duplicates_dropped=0)

    monkeypatch.setattr(processor_mod.ChunkDedupStage, "run", _fake_chunk_dedup_run, raising=True)

    def _fake_chunk_asset_run(self, *, chunks, **_kwargs):  # noqa: ANN001, ANN202
        return processor_mod.ChunkAssetResult(chunks=list(chunks or []), img_ids=[])

    monkeypatch.setattr(processor_mod.ChunkAssetStage, "run", _fake_chunk_asset_run, raising=True)

    def _stop_before_indexing(self, **_kwargs):  # noqa: ANN001, ANN202
        raise RuntimeError("stop-before-indexing")

    monkeypatch.setattr(processor_mod.IndexStage, "run", _stop_before_indexing, raising=True)
    monkeypatch.setattr(processor_mod.Indexer, "delete_chunk_indexes", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        processor_mod.Indexer,
        "delete_chunk_indexes_for_doc_pipeline_key",
        lambda *_a, **_k: None,
        raising=True,
    )

    with pytest.raises(RuntimeError, match="stop-before-indexing"):
        await svc.process_document(
            file_path=file_path,
            document_id=document_id,
            tenant_id=tenant_id,
            parser_backend="basic",
            chunk_strategy="langchain_recursive",
            db=db,
        )

    stages = [s for s, _p in progress_events]
    assert "parsing" in stages
    assert "chunking" in stages
    assert "embedding" in stages
    assert "vector_write" in stages

    assert stages.index("parsing") < stages.index("chunking") < stages.index("embedding") < stages.index("vector_write")
