import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from langchain_core.documents import Document as LCDocument

from app.api.v1 import document_dead_letters, document_processing
from app.models.document import Document
from app.models.ingest_dead_letter import IngestDeadLetter
from app.parsing.processors.processor import (
    CheckpointedRetryRequiredError,
    _indexed_checkpoint_is_reusable,
    _parsed_checkpoint_is_reusable,
)
from app.parsing.processors.support import recovery as recovery_support


class _ReplayQuery:
    def __init__(self, item):  # noqa: ANN001
        self.item = item

    def filter(self, *_args):  # noqa: ANN002,D401
        return self

    def first(self):  # noqa: D401
        return self.item


class _ReplayDB:
    def __init__(self, *, dead_letter, document):  # noqa: ANN001
        self.items = {IngestDeadLetter: dead_letter, Document: document}

    def query(self, model):  # noqa: ANN001
        return _ReplayQuery(self.items.get(model))


def test_truncated_parsed_content_is_not_a_restart_checkpoint() -> None:
    metadata = {
        "ingest_checkpoint": {"version": "1", "stage": "parsed"},
        "parsed_content_persisted": {"cleaned": {"truncated": False}},
    }

    assert _parsed_checkpoint_is_reusable(metadata) is True

    metadata["parsed_content_persisted"]["cleaned"]["truncated"] = True
    assert _parsed_checkpoint_is_reusable(metadata) is False


def test_indexed_checkpoint_requires_matching_stage_and_hashes() -> None:
    metadata = {
        "pipeline_hash": "pipe-1",
        "file_sha256": "abc",
        "ingest_checkpoint": {
            "version": "1",
            "stage": "indexed",
            "pipeline_hash": "pipe-1",
            "file_sha256": "abc",
        },
    }

    assert _indexed_checkpoint_is_reusable(metadata) is True

    metadata["ingest_checkpoint"]["stage"] = "parsed"
    assert _indexed_checkpoint_is_reusable(metadata) is False


class _QuestionDB:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


def test_document_questions_generation_is_opt_in_and_writes_metadata() -> None:
    db = _QuestionDB()
    db_document = type(
        "_Doc",
        (),
        {
            "id": uuid.uuid4(),
            "owner_id": "acct-1",
            "doc_metadata": {
                "document_questions_enabled": True,
                "document_questions_count": 9,
            },
        },
    )()

    recovery_support.maybe_enrich_document_questions(
        db,
        db_document=db_document,
        documents=[LCDocument(page_content="MimirQ supports staged ingestion recovery and audit-friendly retries.")],
    )

    assert len(db_document.doc_metadata["document_questions"]) == 5
    assert db_document.doc_metadata["document_questions_generation"] == {
        "enabled": True,
        "mode": "heuristic",
        "count": 5,
    }
    assert db.commits == 1


@pytest.mark.asyncio
async def test_run_post_completion_kg_marks_ready_and_skipped_channels_when_no_events(monkeypatch: pytest.MonkeyPatch) -> None:
    document = type(
        "_Doc",
        (),
        {
            "id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "doc_metadata": {"pipeline_hash": "pipe-1", "active_pipeline_hash": "pipe-1"},
        },
    )()
    transitions: list[tuple[str, str, bool, str | None]] = []

    class _DB:
        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr(recovery_support.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        recovery_support,
        "transition_document_index_channel",
        lambda _db, *, channel, status, increment_attempt=False, error=None, **_kwargs: transitions.append(
            (channel, status, increment_attempt, error)
        ),
        raising=True,
    )

    async def _extract_events(*_args, **_kwargs):  # noqa: ANN202
        return []

    monkeypatch.setattr(recovery_support, "extract_events", _extract_events, raising=True)

    await recovery_support.run_post_completion_kg(
        db=_DB(),
        db_document=document,
        tenant_id=document.tenant_id,
        document_id=document.id,
        chunk_ids=[uuid.uuid4()],
        db_chunks=[],
        index_options=SimpleNamespace(event_vector_enabled=True, entity_vector_enabled=True),
        pipeline_effective=SimpleNamespace(
            kg_enabled=True,
            kg_python_plugin="",
            chunk_python_plugin="",
            kg_python_params={},
            event_vector_enabled=True,
            entity_vector_enabled=True,
        ),
    )

    assert transitions == [
        ("kg", "processing", True, None),
        ("kg", "ready", False, None),
        ("event_vector", "skipped", False, None),
        ("entity_vector", "skipped", False, None),
    ]


@pytest.mark.asyncio
async def test_run_post_completion_kg_marks_error_when_extraction_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    document = type(
        "_Doc",
        (),
        {
            "id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "doc_metadata": {"pipeline_hash": "pipe-1", "active_pipeline_hash": "pipe-1"},
        },
    )()
    transitions: list[tuple[str, str, bool, str | None]] = []

    class _DB:
        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr(recovery_support.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        recovery_support,
        "transition_document_index_channel",
        lambda _db, *, channel, status, increment_attempt=False, error=None, **_kwargs: transitions.append(
            (channel, status, increment_attempt, error)
        ),
        raising=True,
    )

    async def _extract_events(*_args, **_kwargs):  # noqa: ANN202
        raise RuntimeError("kg failed")

    monkeypatch.setattr(recovery_support, "extract_events", _extract_events, raising=True)

    await recovery_support.run_post_completion_kg(
        db=_DB(),
        db_document=document,
        tenant_id=document.tenant_id,
        document_id=document.id,
        chunk_ids=[uuid.uuid4()],
        db_chunks=[],
        index_options=SimpleNamespace(event_vector_enabled=True, entity_vector_enabled=True),
        pipeline_effective=SimpleNamespace(
            kg_enabled=True,
            kg_python_plugin="",
            chunk_python_plugin="",
            kg_python_params={},
            event_vector_enabled=True,
            entity_vector_enabled=True,
        ),
    )

    assert transitions == [
        ("kg", "processing", True, None),
        ("kg", "error", False, "kg failed"),
    ]


def test_document_questions_generation_is_zero_cost_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _QuestionDB()
    db_document = type(
        "_Doc",
        (),
        {"id": uuid.uuid4(), "owner_id": "acct-1", "doc_metadata": {}},
    )()
    monkeypatch.setattr(recovery_support.settings, "DOCUMENT_QUESTIONS_ENABLED", False, raising=False)

    recovery_support.maybe_enrich_document_questions(
        db,
        db_document=db_document,
        documents=[LCDocument(page_content="This content must not trigger enrichment by default.")],
    )

    assert "document_questions" not in db_document.doc_metadata
    assert db.commits == 0


@pytest.mark.asyncio
async def test_process_document_resumes_from_indexed_checkpoint_without_reindex(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    from app.parsing.processors import processor

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    target_key = f"{document_id}:pipe-1"
    file_path = tmp_path / "resume.txt"
    file_path.write_text("resume", encoding="utf-8")
    db_document = type(
        "_Doc",
        (),
        {
            "id": document_id,
            "tenant_id": tenant_id,
            "dataset_id": None,
            "filename": "resume.txt",
            "file_type": "txt",
            "status": "failed",
            "doc_metadata": {
                "pipeline_hash": "pipe-1",
                "file_sha256": "sha-1",
                "parser_backend": "basic",
                "chunk_strategy": "langchain_recursive",
                "ingest_checkpoint": {
                    "version": "1",
                    "stage": "indexed",
                    "pipeline_hash": "pipe-1",
                    "file_sha256": "sha-1",
                    "doc_pipeline_key": target_key,
                    "total_characters": 11,
                },
            },
        },
    )()
    indexed_chunks = [
        type("_Chunk", (), {"id": uuid.uuid4(), "chunk_index": 0, "content": "hello world"})(),
    ]

    class _Query:
        def __init__(self, result):  # noqa: ANN001
            self._result = result

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def first(self):  # noqa: ANN201
            return self._result

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def all(self):  # noqa: ANN201
            return list(self._result)

    class _DB:
        def query(self, model):  # noqa: ANN001, ANN201
            name = getattr(getattr(model, "class_", model), "__name__", "")
            if name == "Document":
                return _Query(db_document)
            if name == "DocumentChunk":
                return _Query(indexed_chunks)
            raise AssertionError(name)

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    service = processor.DocumentProcessorService()
    status_updates: list[tuple[str, str]] = []
    kg_calls: list[int] = []

    async def _cancel_check(*, force: bool = False) -> bool:  # noqa: ARG001
        return False

    async def _update_status(_db, _tenant_id, _document_id, status, _progress, stage, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        status_updates.append((status, stage))

    async def _run_post_completion_kg(**kwargs):  # noqa: ANN003, ANN202
        kg_calls.append(len(kwargs["chunk_ids"]))

    monkeypatch.setattr(service, "_build_cancel_check", lambda **_kwargs: _cancel_check, raising=True)
    monkeypatch.setattr(service, "_apply_pending_retry_cleanup", lambda *_args, **_kwargs: "applied", raising=True)
    monkeypatch.setattr(service, "_update_status", _update_status, raising=True)
    monkeypatch.setattr(service, "_record_pipeline_effective", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(processor, "resolve_pipeline_effective", lambda **_kwargs: type("_Cfg", (), {"kg_enabled": False})(), raising=True)
    monkeypatch.setattr(processor, "build_indexing_options", lambda _cfg: object(), raising=True)
    monkeypatch.setattr(processor, "run_post_completion_kg", _run_post_completion_kg, raising=True)

    result = await service.process_document(
        file_path=file_path,
        document_id=document_id,
        tenant_id=tenant_id,
        db=_DB(),
    )

    assert result["reason"] == "indexed_checkpoint_resume"
    assert status_updates[0] == ("processing", "parsing")
    assert status_updates[-1] == ("completed", "completed")
    assert kg_calls == [1]


@pytest.mark.asyncio
async def test_update_status_persists_retry_boundary_when_required_ingestion_run_sync_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.parsing.processors import processor

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    db_document = type(
        "_Doc",
        (),
        {
            "id": document_id,
            "tenant_id": tenant_id,
            "status": "processing",
            "current_stage": "vector_write",
            "error_message": None,
            "doc_metadata": {
                "pipeline_hash": "pipe-1",
                "ingest_checkpoint": {"version": "1", "stage": "indexed"},
            },
        },
    )()

    class _Query:
        def populate_existing(self):  # noqa: ANN201
            return self

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def first(self):  # noqa: ANN201
            return db_document

    class _DB:
        def __init__(self) -> None:
            self.commits = 0
            self.rollbacks = 0

        def query(self, _model):  # noqa: ANN001, ANN201
            return _Query()

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            self.rollbacks += 1

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    service = processor.DocumentProcessorService()
    monkeypatch.setattr(
        service,
        "_notify_ingestion_run_status",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("run sync failed")),
        raising=True,
    )

    with pytest.raises(CheckpointedRetryRequiredError, match="ingestion_run_status_update_failed"):
        await service._update_status(
            _DB(),
            tenant_id,
            document_id,
            "completed",
            100,
            "completed",
        )

    assert db_document.status == "failed"
    assert db_document.current_stage == "finalizing"
    assert db_document.error_message == "ingestion_run_status_update_failed"
    assert db_document.doc_metadata["ingest_resume_required"]["reason"] == "ingestion_run_status_update_failed"


@pytest.mark.parametrize(("document_status", "expected_force"), [("failed", False), ("quarantined", False), ("completed", True)])
def test_dead_letter_replay_only_forces_completed_documents(
    monkeypatch: pytest.MonkeyPatch,
    document_status: str,
    expected_force: bool,
) -> None:
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    dead_letter = IngestDeadLetter(id=uuid.uuid4(), tenant_id=tenant_id, document_id=document_id, status="open")
    document = Document(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        filename="document.txt",
        file_type="txt",
        file_size=1,
        file_path="/tmp/document.txt",
        status=document_status,
    )
    captured: dict[str, object] = {}

    async def retry(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return {"status": "queued"}

    monkeypatch.setattr(document_dead_letters.DatasetService, "ensure_member", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        document_dead_letters,
        "assert_document_writable_for_lifecycle",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(document_dead_letters, "mark_dead_letter_replayed", lambda _db, *, dead_letter: dead_letter)
    monkeypatch.setattr(document_processing, "retry_document_processing", retry)

    asyncio.run(
        document_dead_letters.replay_ingest_dead_letter(
            dead_letter.id,
            BackgroundTasks(),
            tenant_id=tenant_id,
            account_id="editor",
            db=_ReplayDB(dead_letter=dead_letter, document=document),
        )
    )

    assert captured["force"] is expected_force
