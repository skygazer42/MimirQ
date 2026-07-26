import io
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import UploadFile

import app  # noqa: F401
from app.api.v1 import documents as documents_module

document_upload = documents_module.document_upload


def _build_overrides_form() -> document_upload.PipelineOverridesFormFields:
    return document_upload.PipelineOverridesFormFields(
        governance_enabled=None,
        governance_remove_toc_lines=None,
        governance_remove_noise_lines=None,
        governance_unwrap_lines=None,
        governance_remove_common_lines=None,
        governance_unwrap_max_line_length=None,
        governance_noise_min_chars=None,
        governance_noise_ratio_threshold=None,
        governance_common_lines_min_docs=None,
        governance_common_lines_min_ratio=None,
        chunk_size=None,
        chunk_overlap=None,
        chunk_vector_enabled=None,
        bm25_index_enabled=None,
        kg_enabled=None,
        event_vector_enabled=None,
        entity_vector_enabled=None,
    )


def _make_upload(filename: str, content: str = "hello") -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(content.encode("utf-8")))


def _patch_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import tenant_quota_service

    monkeypatch.setattr(
        tenant_quota_service,
        "enforce_tenant_upload_quotas",
        lambda *args, **kwargs: None,
        raising=True,
    )


def _patch_minimal_document_resolution(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dataset_id: uuid.UUID,
    pipeline_hash: str = "pipeline-hash",
) -> SimpleNamespace:
    dataset = SimpleNamespace(id=dataset_id, dataset_metadata={})
    monkeypatch.setattr(documents_module, "_resolve_writable_dataset", lambda *args, **kwargs: dataset, raising=True)
    monkeypatch.setattr(documents_module, "_parse_pipeline_json", lambda raw: None, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_to_pipeline_options",
        lambda *args, **kwargs: documents_module.PipelineOptions(),
        raising=True,
    )
    monkeypatch.setattr(documents_module, "match_ingestion_rule", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module.parser_factory,
        "resolve_backend",
        lambda *args, **kwargs: "auto",
        raising=True,
    )
    monkeypatch.setattr(
        documents_module.chunker_factory,
        "resolve_strategy",
        lambda *args, **kwargs: "langchain_recursive",
        raising=True,
    )
    monkeypatch.setattr(
        documents_module,
        "resolve_pipeline_effective",
        lambda *args, **kwargs: SimpleNamespace(chunk_size=1000, chunk_overlap=100),
        raising=True,
    )
    monkeypatch.setattr(documents_module, "_validate_chunk_params", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(documents_module, "upsert_pipeline_metadata", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(documents_module, "_compute_pipeline_hash", lambda meta: pipeline_hash, raising=True)
    monkeypatch.setattr(documents_module, "_find_duplicate_document", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(documents_module, "_find_duplicate_document_by_sha", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(documents_module.IngestionRunService, "create_run", lambda *args, **kwargs: None, raising=True)
    return dataset


async def _fake_save_upload_file_with_hash(file: UploadFile, file_path: Path, max_bytes: int) -> tuple[int, str]:
    data = await file.read()
    await file.seek(0)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(data)
    return len(data), f"sha-{file.filename}"


class _DetachedStatusDocument:
    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        self.id = kwargs["id"]
        self.filename = kwargs["filename"]
        self.doc_metadata = kwargs["doc_metadata"]
        self._status = kwargs["status"]
        self._session = None

    @property
    def status(self) -> str:
        if self._session is not None and getattr(self._session, "closed", False):
            raise RuntimeError("detached status access")
        return self._status


class _FakeItemSession:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _OuterQuery:
    def __init__(self, document) -> None:  # noqa: ANN001
        self.document = document

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return self

    def first(self):  # noqa: ANN201
        return self.document


class _OuterDB:
    def __init__(self, document) -> None:  # noqa: ANN001
        self.document = document
        self.added: list[object] = []

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def query(self, _model):  # noqa: ANN001, ANN201
        return _OuterQuery(self.document)


@pytest.mark.asyncio
async def test_upload_batch_rejects_nonpositive_max_concurrent() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await document_upload.upload_documents_batch(
            background_tasks=BackgroundTasks(),
            files=[_make_upload("bad.txt")],
            form=document_upload.UploadDocumentsBatchFormFields(
                parser_backend="auto",
                chunk_strategy="langchain_recursive",
                pipeline=None,
                dataset_id=None,
                precheck_first=False,
                precheck_only=False,
                upload_only=True,
                user_metadata_map=None,
                max_concurrent=0,
            ),
            overrides_form=_build_overrides_form(),
            tenant_id=uuid.uuid4(),
            account_id="acct-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "max_concurrent must be at least 1"


@pytest.mark.asyncio
async def test_upload_batch_uses_isolated_item_sessions_and_response_survives_closed_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outer_db = SimpleNamespace()
    dataset_id = uuid.uuid4()
    item_sessions: list[_FakeItemSession] = []
    persisted_sessions: list[_FakeItemSession] = []

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(documents_module, "DBDocument", _DetachedStatusDocument, raising=True)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)

    def _new_item_session() -> _FakeItemSession:
        session = _FakeItemSession(name=f"item-{len(item_sessions) + 1}")
        item_sessions.append(session)
        return session

    async def _persist(db, db_document, *, file_path: Path) -> None:  # noqa: ANN001
        persisted_sessions.append(db)
        db_document._session = db

    async def _store(file_path: Path, **_kwargs) -> str:  # noqa: ANN003, ANN202
        return str(file_path)

    monkeypatch.setattr(documents_module, "SessionLocal", _new_item_session, raising=True)
    monkeypatch.setattr(document_upload, "_persist_uploaded_document", _persist, raising=True)
    monkeypatch.setattr(document_upload, "_store_document_source", _store, raising=True)

    result = await document_upload.upload_documents_batch(
        background_tasks=BackgroundTasks(),
        files=[_make_upload("one.txt"), _make_upload("two.txt")],
        form=document_upload.UploadDocumentsBatchFormFields(
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
            pipeline=None,
            dataset_id=dataset_id,
            precheck_first=False,
            precheck_only=False,
            upload_only=True,
            user_metadata_map=None,
            max_concurrent=2,
        ),
        overrides_form=_build_overrides_form(),
        tenant_id=uuid.uuid4(),
        account_id="acct-1",
        db=outer_db,
    )

    assert result["successful_count"] == 2
    assert [entry["filename"] for entry in result["successful"]] == ["one.txt", "two.txt"]
    assert [entry["status"] for entry in result["successful"]] == ["pending", "pending"]
    assert len(item_sessions) == 2
    assert len(persisted_sessions) == 2
    assert {id(session) for session in persisted_sessions} == {id(session) for session in item_sessions}
    assert all(session.closed for session in item_sessions)
    assert all(session is not outer_db for session in persisted_sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize("precheck_first", [False, True])
async def test_upload_batch_closes_intake_after_attaching_successes_in_both_branches(
    monkeypatch: pytest.MonkeyPatch,
    precheck_first: bool,
) -> None:
    dataset_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    duplicate = SimpleNamespace(id=uuid.uuid4(), filename="dup.txt", status="completed", doc_metadata={})
    ingestion_run = SimpleNamespace(id=uuid.uuid4())
    outer_db = _OuterDB(duplicate)
    item_sessions: list[_FakeItemSession] = []
    events: list[str] = []
    close_calls: list[dict[str, object]] = []

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_find_duplicate_document",
        lambda *_args, file_sha256=None, **_kwargs: duplicate if file_sha256 == "sha-dup.txt" else None,
        raising=True,
    )
    monkeypatch.setattr(documents_module.IngestionRunService, "create_run", lambda *args, **kwargs: ingestion_run, raising=True)

    def _add_document(*_args, **kwargs) -> None:  # noqa: ANN003
        events.append(f"add:{kwargs['document_id']}")

    def _close_intake(*_args, **kwargs) -> None:  # noqa: ANN003
        events.append("close")
        close_calls.append(kwargs)

    monkeypatch.setattr(documents_module.IngestionRunService, "add_document", _add_document, raising=True)
    monkeypatch.setattr(documents_module.IngestionRunService, "close_intake", _close_intake, raising=True)
    monkeypatch.setattr(documents_module, "run_dataset_precheck_scan", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(documents_module, "apply_ingestion_policy_suggestion", lambda *_args, **_kwargs: None, raising=True)

    def _new_item_session() -> _FakeItemSession:
        session = _FakeItemSession(name=f"item-{len(item_sessions) + 1}")
        item_sessions.append(session)
        return session

    monkeypatch.setattr(documents_module, "SessionLocal", _new_item_session, raising=True)

    result = await document_upload.upload_documents_batch(
        background_tasks=BackgroundTasks(),
        files=[_make_upload("dup.txt"), _make_upload("bad.exe")],
        form=document_upload.UploadDocumentsBatchFormFields(
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
            pipeline=None,
            dataset_id=dataset_id,
            precheck_first=precheck_first,
            precheck_only=False,
            upload_only=False,
            user_metadata_map=None,
            max_concurrent=2,
        ),
        overrides_form=_build_overrides_form(),
        tenant_id=tenant_id,
        account_id="acct-1",
        db=outer_db,
    )

    assert result["successful_count"] == 1
    assert result["failed_count"] == 1
    assert result["successful"][0]["document_id"] == str(duplicate.id)
    assert result["failed"][0]["filename"] == "bad.exe"
    assert events == [f"add:{duplicate.id}", "close"]
    assert len(close_calls) == 1
    assert close_calls[0]["tenant_id"] == tenant_id
    assert close_calls[0]["run_id"] == ingestion_run.id
    assert close_calls[0]["attempted_inputs"] == 2
    assert close_calls[0]["rejected_inputs"] == 1
    assert close_calls[0]["rejection_reasons"] == [result["failed"][0]["error"]]
    assert all(session.closed for session in item_sessions)


@pytest.mark.asyncio
async def test_single_upload_releases_ingest_lock_on_dedup_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    released: list[tuple[str, str]] = []

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_find_duplicate_document",
        lambda *args, **kwargs: SimpleNamespace(id=uuid.uuid4(), status="completed", doc_metadata={}),
        raising=True,
    )

    async def _queue() -> object:
        return object()

    async def _acquire(redis, *, key: str, value: str, ttl_sec: int, fail_open: bool = True) -> bool:  # noqa: ANN001
        return True

    async def _release(redis, *, key: str, value: str) -> None:  # noqa: ANN001
        released.append((key, value))

    monkeypatch.setattr("app.tasks.queue.get_queue", _queue, raising=False)
    monkeypatch.setattr("app.tasks.locks.acquire_lock", _acquire, raising=False)
    monkeypatch.setattr("app.tasks.locks.release_lock", _release, raising=False)

    result = await document_upload.upload_document(
        background_tasks=BackgroundTasks(),
        file=_make_upload("dup.txt"),
        form=document_upload.UploadDocumentFormFields(
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
            pipeline=None,
            dataset_id=dataset_id,
            user_metadata=None,
        ),
        overrides_form=_build_overrides_form(),
        tenant_id=tenant_id,
        account_id="acct-1",
        db=SimpleNamespace(commit=lambda: None, refresh=lambda *_args: None),
    )

    assert result.id
    assert len(released) == 1
    assert released[0][0].startswith(f"lock:ingest:{tenant_id}:{dataset_id}:sha-dup.txt:pipeline-hash")


@pytest.mark.asyncio
async def test_single_upload_uses_timeout_based_ingest_lock_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    captured_ttls: list[int] = []

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_JOB_TIMEOUT_SEC", 4_000, raising=False)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_find_duplicate_document",
        lambda *args, **kwargs: SimpleNamespace(id=uuid.uuid4(), status="completed", doc_metadata={}),
        raising=True,
    )

    async def _queue() -> object:
        return object()

    async def _acquire(redis, *, key: str, value: str, ttl_sec: int, fail_open: bool = True) -> bool:  # noqa: ANN001
        captured_ttls.append(ttl_sec)
        return True

    async def _release(redis, *, key: str, value: str) -> None:  # noqa: ANN001
        return None

    monkeypatch.setattr("app.tasks.queue.get_queue", _queue, raising=False)
    monkeypatch.setattr("app.tasks.locks.acquire_lock", _acquire, raising=False)
    monkeypatch.setattr("app.tasks.locks.release_lock", _release, raising=False)

    result = await document_upload.upload_document(
        background_tasks=BackgroundTasks(),
        file=_make_upload("dup.txt"),
        form=document_upload.UploadDocumentFormFields(
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
            pipeline=None,
            dataset_id=dataset_id,
            user_metadata=None,
        ),
        overrides_form=_build_overrides_form(),
        tenant_id=tenant_id,
        account_id="acct-1",
        db=SimpleNamespace(commit=lambda: None, refresh=lambda *_args: None),
    )

    assert result.id
    assert captured_ttls == [4_060]


@pytest.mark.asyncio
async def test_ingest_lock_contention_falls_through_to_database_dedup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata: dict[str, str] = {}
    lease = document_upload._IngestLockLease()

    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", True, raising=False)

    async def _queue() -> object:
        return object()

    async def _acquire(*_args, **_kwargs) -> bool:  # noqa: ANN002, ANN003
        return False

    monkeypatch.setattr("app.tasks.queue.get_queue", _queue, raising=False)
    monkeypatch.setattr("app.tasks.locks.acquire_lock", _acquire, raising=False)

    await document_upload._maybe_acquire_ingest_lock(
        tenant_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        file_sha256="sha-1",
        pipeline_hash="pipeline-1",
        account_id="acct-1",
        doc_metadata=metadata,
        ingest_lock=lease,
    )

    assert metadata == {}
    assert lease.redis is None


@pytest.mark.asyncio
async def test_single_upload_returns_pending_same_pipeline_follower(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    duplicate = SimpleNamespace(
        id=uuid.uuid4(),
        filename="dup.txt",
        status="processing",
        doc_metadata={"file_sha256": "sha-dup.txt", "pipeline_hash": "pipeline-hash"},
        dedup_key="sha-dup.txt:pipeline-hash",
    )

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_find_duplicate_document_by_sha",
        lambda *args, **kwargs: duplicate,
        raising=True,
    )

    result = await document_upload.upload_document(
        background_tasks=BackgroundTasks(),
        file=_make_upload("dup.txt"),
        form=document_upload.UploadDocumentFormFields(
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
            pipeline=None,
            dataset_id=dataset_id,
            user_metadata=None,
        ),
        overrides_form=_build_overrides_form(),
        tenant_id=tenant_id,
        account_id="acct-1",
        db=SimpleNamespace(),
    )

    assert result is duplicate


@pytest.mark.asyncio
async def test_single_upload_keeps_pending_different_pipeline_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    duplicate = SimpleNamespace(
        id=uuid.uuid4(),
        filename="dup.txt",
        status="pending",
        doc_metadata={"file_sha256": "sha-dup.txt", "pipeline_hash": "different-pipeline"},
        dedup_key="sha-dup.txt:different-pipeline",
    )

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_find_duplicate_document_by_sha",
        lambda *args, **kwargs: duplicate,
        raising=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await document_upload.upload_document(
            background_tasks=BackgroundTasks(),
            file=_make_upload("dup.txt"),
            form=document_upload.UploadDocumentFormFields(
                parser_backend="auto",
                chunk_strategy="langchain_recursive",
                pipeline=None,
                dataset_id=dataset_id,
                user_metadata=None,
            ),
            overrides_form=_build_overrides_form(),
            tenant_id=tenant_id,
            account_id="acct-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == documents_module.DUPLICATE_DOCUMENT_PROCESSING_DETAIL


@pytest.mark.asyncio
async def test_ingest_lock_is_skipped_when_upload_dedup_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata: dict[str, str] = {}
    lease = document_upload._IngestLockLease()

    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", False, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", True, raising=False)

    async def _queue() -> object:
        raise AssertionError("queue probe should be skipped when upload dedup is disabled")

    monkeypatch.setattr("app.tasks.queue.get_queue", _queue, raising=False)

    await document_upload._maybe_acquire_ingest_lock(
        tenant_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        file_sha256="sha-1",
        pipeline_hash="pipeline-1",
        account_id="acct-1",
        doc_metadata=metadata,
        ingest_lock=lease,
    )

    assert metadata == {}
    assert lease.redis is None


@pytest.mark.asyncio
async def test_single_upload_fails_closed_when_ingest_lock_queue_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = uuid.uuid4()

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)

    async def _queue() -> object:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("app.tasks.queue.get_queue", _queue, raising=False)

    with pytest.raises(HTTPException) as exc_info:
        await document_upload.upload_document(
            background_tasks=BackgroundTasks(),
            file=_make_upload("queue-down.txt"),
            form=document_upload.UploadDocumentFormFields(
                parser_backend="auto",
                chunk_strategy="langchain_recursive",
                pipeline=None,
                dataset_id=dataset_id,
                user_metadata=None,
            ),
            overrides_form=_build_overrides_form(),
            tenant_id=uuid.uuid4(),
            account_id="acct-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == document_upload.INGEST_LOCK_UNAVAILABLE_DETAIL


@pytest.mark.asyncio
async def test_single_upload_fails_closed_when_ingest_lock_set_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = uuid.uuid4()

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)

    class _FailingRedis:
        async def set(self, *_args, **_kwargs) -> bool:  # noqa: ANN002, ANN003
            raise RuntimeError("set failed")

    async def _queue() -> object:
        return _FailingRedis()

    monkeypatch.setattr("app.tasks.queue.get_queue", _queue, raising=False)

    with pytest.raises(HTTPException) as exc_info:
        await document_upload.upload_document(
            background_tasks=BackgroundTasks(),
            file=_make_upload("set-fails.txt"),
            form=document_upload.UploadDocumentFormFields(
                parser_backend="auto",
                chunk_strategy="langchain_recursive",
                pipeline=None,
                dataset_id=dataset_id,
                user_metadata=None,
            ),
            overrides_form=_build_overrides_form(),
            tenant_id=uuid.uuid4(),
            account_id="acct-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == document_upload.INGEST_LOCK_UNAVAILABLE_DETAIL


@pytest.mark.asyncio
async def test_single_upload_skips_ingest_lock_when_queue_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = uuid.uuid4()

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(documents_module, "DBDocument", _DetachedStatusDocument, raising=True)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)

    async def _queue() -> object:
        raise AssertionError("queue probe should be skipped when disabled")

    async def _persist(db, db_document, *, file_path: Path) -> None:  # noqa: ANN001
        db_document._session = db

    async def _store(file_path: Path, **_kwargs) -> str:  # noqa: ANN003, ANN202
        return str(file_path)

    async def _schedule(**_kwargs) -> bool:  # noqa: ANN003, ANN202
        return True

    monkeypatch.setattr("app.tasks.queue.get_queue", _queue, raising=False)
    monkeypatch.setattr(document_upload, "_persist_uploaded_document", _persist, raising=True)
    monkeypatch.setattr(document_upload, "_store_document_source", _store, raising=True)
    monkeypatch.setattr(document_upload, "_schedule_document_processing", _schedule, raising=True)

    db = _FakeItemSession("single-disabled")
    result = await document_upload.upload_document(
        background_tasks=BackgroundTasks(),
        file=_make_upload("local-disabled.txt"),
        form=document_upload.UploadDocumentFormFields(
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
            pipeline=None,
            dataset_id=dataset_id,
            user_metadata=None,
        ),
        overrides_form=_build_overrides_form(),
        tenant_id=uuid.uuid4(),
        account_id="acct-1",
        db=db,
    )

    assert result.id


@pytest.mark.asyncio
async def test_single_upload_releases_ingest_lock_without_worker_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = uuid.uuid4()
    released: list[tuple[str, str]] = []

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module, "DBDocument", _DetachedStatusDocument, raising=True)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)

    async def _queue() -> object:
        return object()

    async def _acquire(redis, *, key: str, value: str, ttl_sec: int, fail_open: bool = True) -> bool:  # noqa: ANN001
        return True

    async def _release(redis, *, key: str, value: str) -> None:  # noqa: ANN001
        released.append((key, value))

    async def _persist(db, db_document, *, file_path: Path) -> None:  # noqa: ANN001
        db_document._session = db

    async def _store(file_path: Path, **_kwargs) -> str:  # noqa: ANN003, ANN202
        return str(file_path)

    async def _schedule(**kwargs) -> bool:  # noqa: ANN003, ANN202
        return True

    monkeypatch.setattr("app.tasks.queue.get_queue", _queue, raising=False)
    monkeypatch.setattr("app.tasks.locks.acquire_lock", _acquire, raising=False)
    monkeypatch.setattr("app.tasks.locks.release_lock", _release, raising=False)
    monkeypatch.setattr(document_upload, "_persist_uploaded_document", _persist, raising=True)
    monkeypatch.setattr(document_upload, "_store_document_source", _store, raising=True)
    monkeypatch.setattr(document_upload, "_schedule_document_processing", _schedule, raising=True)

    db = _FakeItemSession("single")
    result = await document_upload.upload_document(
        background_tasks=BackgroundTasks(),
        file=_make_upload("local.txt"),
        form=document_upload.UploadDocumentFormFields(
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
            pipeline=None,
            dataset_id=dataset_id,
            user_metadata=None,
        ),
        overrides_form=_build_overrides_form(),
        tenant_id=uuid.uuid4(),
        account_id="acct-1",
        db=db,
    )

    assert result.id
    assert len(released) == 1


@pytest.mark.asyncio
async def test_single_upload_hands_retry_ingest_lock_to_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = uuid.uuid4()
    released: list[tuple[str, str]] = []
    duplicate = SimpleNamespace(
        id=uuid.uuid4(),
        filename="queued.txt",
        status="completed",
        doc_metadata={},
    )

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_find_duplicate_document_by_sha",
        lambda *args, **kwargs: duplicate,
        raising=True,
    )

    async def _queue() -> object:
        return object()

    async def _acquire(redis, *, key: str, value: str, ttl_sec: int, fail_open: bool = True) -> bool:  # noqa: ANN001
        return True

    async def _release(redis, *, key: str, value: str) -> None:  # noqa: ANN001
        released.append((key, value))

    async def _retry(**_kwargs) -> None:  # noqa: ANN003
        meta = dict(duplicate.doc_metadata or {})
        meta["task_id"] = "task-1"
        duplicate.doc_metadata = meta

    monkeypatch.setattr("app.tasks.queue.get_queue", _queue, raising=False)
    monkeypatch.setattr("app.tasks.locks.acquire_lock", _acquire, raising=False)
    monkeypatch.setattr("app.tasks.locks.release_lock", _release, raising=False)
    monkeypatch.setattr(documents_module, "retry_document_processing", _retry, raising=True)

    db = SimpleNamespace(commit=lambda: None, refresh=lambda *_args: None)
    result = await document_upload.upload_document(
        background_tasks=BackgroundTasks(),
        file=_make_upload("queued.txt"),
        form=document_upload.UploadDocumentFormFields(
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
            pipeline=None,
            dataset_id=dataset_id,
            user_metadata=None,
        ),
        overrides_form=_build_overrides_form(),
        tenant_id=uuid.uuid4(),
        account_id="acct-1",
        db=db,
    )

    assert result.id
    assert released == []
    assert duplicate.doc_metadata["ingest_lock_key"].startswith("lock:ingest:")
    assert duplicate.doc_metadata["ingest_lock_value"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "processing"])
async def test_single_upload_reuses_matching_sha_only_duplicate_while_pending_or_processing(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    dataset_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    duplicate_document = SimpleNamespace(
        id=uuid.uuid4(),
        filename="dup.txt",
        status=status,
        doc_metadata={"file_sha256": "sha-dup.txt", "pipeline_hash": "pipeline-hash"},
        dedup_key="sha-dup.txt:pipeline-hash",
    )

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)
    monkeypatch.setattr(documents_module.IngestionRunService, "create_run", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(documents_module, "_find_duplicate_document", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_find_duplicate_document_by_sha",
        lambda *args, **kwargs: duplicate_document,
        raising=True,
    )

    result = await document_upload.upload_document(
        background_tasks=BackgroundTasks(),
        file=_make_upload("dup.txt"),
        form=document_upload.UploadDocumentFormFields(
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
            pipeline=None,
            dataset_id=dataset_id,
            user_metadata=None,
        ),
        overrides_form=_build_overrides_form(),
        tenant_id=tenant_id,
        account_id="acct-1",
        db=SimpleNamespace(commit=lambda: None, refresh=lambda *_args: None),
    )

    assert result.id == duplicate_document.id


@pytest.mark.asyncio
async def test_single_upload_releases_ingest_lock_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = uuid.uuid4()
    released: list[tuple[str, str]] = []

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)

    async def _queue() -> object:
        return object()

    async def _acquire(redis, *, key: str, value: str, ttl_sec: int, fail_open: bool = True) -> bool:  # noqa: ANN001
        return True

    async def _release(redis, *, key: str, value: str) -> None:  # noqa: ANN001
        released.append((key, value))

    async def _boom(**kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("store failed")

    monkeypatch.setattr("app.tasks.queue.get_queue", _queue, raising=False)
    monkeypatch.setattr("app.tasks.locks.acquire_lock", _acquire, raising=False)
    monkeypatch.setattr("app.tasks.locks.release_lock", _release, raising=False)
    monkeypatch.setattr(document_upload, "_store_document_source", _boom, raising=True)

    with pytest.raises(RuntimeError, match="store failed"):
        await document_upload.upload_document(
            background_tasks=BackgroundTasks(),
            file=_make_upload("boom.txt"),
            form=document_upload.UploadDocumentFormFields(
                parser_backend="auto",
                chunk_strategy="langchain_recursive",
                pipeline=None,
                dataset_id=dataset_id,
                user_metadata=None,
            ),
            overrides_form=_build_overrides_form(),
            tenant_id=uuid.uuid4(),
            account_id="acct-1",
            db=SimpleNamespace(),
        )

    assert len(released) == 1


@pytest.mark.asyncio
async def test_persist_uploaded_document_reuses_duplicate_after_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    duplicate = SimpleNamespace(id=uuid.uuid4(), filename="existing.txt", status="pending", doc_metadata={})
    file_path = tmp_path / "upload.txt"
    file_path.write_text("payload", encoding="utf-8")

    class _FakeDB:
        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        class _Diag:
            constraint_name = document_upload.DOCUMENT_DEDUP_CONSTRAINT_NAME

        class _OrigError(Exception):
            def __init__(self) -> None:
                super().__init__(document_upload.DOCUMENT_DEDUP_CONSTRAINT_NAME)
                self.diag = _FakeDB._Diag()

        def commit(self) -> None:
            raise IntegrityError("insert", {}, _FakeDB._OrigError())

        def rollback(self) -> None:
            return None

    monkeypatch.setattr(
        documents_module,
        "_find_duplicate_document",
        lambda *args, **kwargs: duplicate,
        raising=True,
    )

    db_document = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        doc_metadata={"file_sha256": "sha-1", "pipeline_hash": "pipe-1"},
        file_path=str(file_path),
    )

    with pytest.raises(document_upload._DuplicatePersistedDocumentError) as exc_info:
        await document_upload._persist_uploaded_document(_FakeDB(), db_document, file_path=file_path)

    assert exc_info.value.document is duplicate
    assert not file_path.exists()


@pytest.mark.asyncio
async def test_persist_uploaded_document_cleans_source_for_unrelated_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "upload.txt"
    file_path.write_text("payload", encoding="utf-8")
    cleaned: list[str] = []

    async def _cleanup(stored_path: str, **_kwargs) -> None:  # noqa: ANN003
        cleaned.append(stored_path)

    class _FakeDB:
        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            raise IntegrityError("insert", {}, RuntimeError("uq_documents_other_constraint"))

        def rollback(self) -> None:
            return None

    monkeypatch.setattr(document_upload, "_cleanup_unpersisted_source", _cleanup, raising=True)
    db_document = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        doc_metadata={"file_sha256": "sha-1", "pipeline_hash": "pipe-1"},
        file_path="minio://documents/upload.txt",
    )

    with pytest.raises(IntegrityError, match="uq_documents_other_constraint"):
        await document_upload._persist_uploaded_document(_FakeDB(), db_document, file_path=file_path)

    assert cleaned == ["minio://documents/upload.txt"]
    assert not file_path.exists()


@pytest.mark.asyncio
async def test_failed_persisted_duplicate_reuses_existing_retry_path(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    document = SimpleNamespace(id=uuid.uuid4(), status="failed")
    retried: list[dict] = []

    async def _retry(**kwargs) -> None:  # noqa: ANN003
        retried.append(kwargs)

    class _FakeDB:
        def refresh(self, _document) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr(documents_module, "retry_document_processing", _retry, raising=True)
    db = _FakeDB()
    background_tasks = BackgroundTasks()

    await document_upload._retry_failed_persisted_duplicate(
        document,
        background_tasks=background_tasks,
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert retried == [
        {
            "document_id": document.id,
            "background_tasks": background_tasks,
            "force": True,
            "skip_if_unchanged": True,
            "tenant_id": tenant_id,
            "account_id": "acct-1",
            "db": db,
        }
    ]


@pytest.mark.asyncio
async def test_single_upload_preserves_local_source_when_queue_handoff_fails_after_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_id = uuid.uuid4()
    captured_paths: list[Path] = []

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(document_upload.settings, "MINIO_DOCUMENTS_ENABLED", False, raising=False)
    monkeypatch.setattr(documents_module, "DBDocument", _DetachedStatusDocument, raising=True)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)

    async def _queue() -> object:
        return object()

    async def _acquire(redis, *, key: str, value: str, ttl_sec: int, fail_open: bool = True) -> bool:  # noqa: ANN001
        return True

    async def _persist(db, db_document, *, file_path: Path) -> None:  # noqa: ANN001
        captured_paths.append(file_path)
        db_document._session = db

    async def _store(file_path: Path, **_kwargs) -> str:  # noqa: ANN003, ANN202
        return str(file_path)

    async def _schedule(**kwargs) -> bool:  # noqa: ANN003, ANN202
        assert kwargs["file_path"].exists()
        raise HTTPException(
            status_code=503,
            detail=documents_module.DOCUMENT_PROCESSING_QUEUE_UNAVAILABLE_DETAIL,
        )

    monkeypatch.setattr("app.tasks.queue.get_queue", _queue, raising=False)
    monkeypatch.setattr("app.tasks.locks.acquire_lock", _acquire, raising=False)
    monkeypatch.setattr(document_upload, "_persist_uploaded_document", _persist, raising=True)
    monkeypatch.setattr(document_upload, "_store_document_source", _store, raising=True)
    monkeypatch.setattr(document_upload, "_schedule_document_processing", _schedule, raising=True)

    db = _FakeItemSession("single-local-queue-fail")
    with pytest.raises(HTTPException) as exc_info:
        await document_upload.upload_document(
            background_tasks=BackgroundTasks(),
            file=_make_upload("local-queue-fail.txt"),
            form=document_upload.UploadDocumentFormFields(
                parser_backend="auto",
                chunk_strategy="langchain_recursive",
                pipeline=None,
                dataset_id=dataset_id,
                user_metadata=None,
            ),
            overrides_form=_build_overrides_form(),
            tenant_id=uuid.uuid4(),
            account_id="acct-1",
            db=db,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == documents_module.DOCUMENT_PROCESSING_QUEUE_UNAVAILABLE_DETAIL
    assert len(captured_paths) == 1
    assert captured_paths[0].exists()


@pytest.mark.asyncio
async def test_batch_upload_hands_retry_ingest_lock_to_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = uuid.uuid4()
    duplicate = SimpleNamespace(
        id=uuid.uuid4(),
        filename="batch.txt",
        status="completed",
        doc_metadata={},
    )
    released: list[tuple[str, str]] = []

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_find_duplicate_document_by_sha",
        lambda *args, **kwargs: duplicate,
        raising=True,
    )
    monkeypatch.setattr(
        documents_module,
        "SessionLocal",
        lambda: SimpleNamespace(commit=lambda: None, refresh=lambda *_args: None, close=lambda: None),
        raising=True,
    )

    async def _queue() -> object:
        return object()

    async def _acquire(redis, *, key: str, value: str, ttl_sec: int, fail_open: bool = True) -> bool:  # noqa: ANN001
        return True

    async def _release(redis, *, key: str, value: str) -> None:  # noqa: ANN001
        released.append((key, value))

    async def _retry(**_kwargs) -> None:  # noqa: ANN003
        meta = dict(duplicate.doc_metadata or {})
        meta["task_id"] = "task-1"
        duplicate.doc_metadata = meta

    monkeypatch.setattr("app.tasks.queue.get_queue", _queue, raising=False)
    monkeypatch.setattr("app.tasks.locks.acquire_lock", _acquire, raising=False)
    monkeypatch.setattr("app.tasks.locks.release_lock", _release, raising=False)
    monkeypatch.setattr(documents_module, "retry_document_processing", _retry, raising=True)

    result = await document_upload.upload_documents_batch(
        background_tasks=BackgroundTasks(),
        files=[_make_upload("batch.txt")],
        form=document_upload.UploadDocumentsBatchFormFields(
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
            pipeline=None,
            dataset_id=dataset_id,
            precheck_first=False,
            precheck_only=False,
            upload_only=False,
            user_metadata_map=None,
            max_concurrent=1,
        ),
        overrides_form=_build_overrides_form(),
        tenant_id=uuid.uuid4(),
        account_id="acct-1",
        db=SimpleNamespace(),
    )

    assert result["successful_count"] == 1
    assert released == []
    assert duplicate.doc_metadata["task_id"] == "task-1"
    assert duplicate.doc_metadata["ingest_lock_key"].startswith("lock:ingest:")
    assert duplicate.doc_metadata["ingest_lock_value"]


@pytest.mark.asyncio
@pytest.mark.parametrize("precheck_first", [False, True])
@pytest.mark.parametrize("same_pipeline", [False, True])
async def test_batch_pending_duplicate_respects_pipeline_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    precheck_first: bool,
    same_pipeline: bool,
) -> None:
    dataset_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    existing_pipeline = "pipeline-hash" if same_pipeline else "different-pipeline"
    duplicate = SimpleNamespace(
        id=uuid.uuid4(),
        filename="batch.txt",
        status="processing",
        doc_metadata={"file_sha256": "sha-batch.txt", "pipeline_hash": existing_pipeline},
        dedup_key=f"sha-batch.txt:{existing_pipeline}",
    )

    class _OuterDB:
        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(document_upload.settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(document_upload.settings, "MINIO_DOCUMENTS_ENABLED", False, raising=False)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_find_duplicate_document_by_sha",
        lambda *args, **kwargs: duplicate,
        raising=True,
    )
    monkeypatch.setattr(
        documents_module,
        "SessionLocal",
        lambda: SimpleNamespace(commit=lambda: None, refresh=lambda *_args: None, close=lambda: None),
        raising=True,
    )
    monkeypatch.setattr(documents_module, "run_dataset_precheck_scan", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(documents_module, "apply_ingestion_policy_suggestion", lambda *_args, **_kwargs: None, raising=True)

    result = await document_upload.upload_documents_batch(
        background_tasks=BackgroundTasks(),
        files=[_make_upload("batch.txt")],
        form=document_upload.UploadDocumentsBatchFormFields(
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
            pipeline=None,
            dataset_id=dataset_id,
            precheck_first=precheck_first,
            precheck_only=False,
            upload_only=False,
            user_metadata_map=None,
            max_concurrent=1,
        ),
        overrides_form=_build_overrides_form(),
        tenant_id=tenant_id,
        account_id="acct-1",
        db=_OuterDB(),
    )

    if same_pipeline:
        assert result["successful_count"] == 1
        assert result["failed_count"] == 0
        assert result["successful"][0]["document_id"] == str(duplicate.id)
    else:
        assert result["successful_count"] == 0
        assert result["failed_count"] == 1
        error = result["failed"][0]["error"]
        assert error.startswith("409:")
        assert error.endswith(documents_module.DUPLICATE_DOCUMENT_PROCESSING_DETAIL)


@pytest.mark.asyncio
async def test_single_upload_returns_existing_document_after_dedup_constraint_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    duplicate_document = SimpleNamespace(
        id=uuid.uuid4(),
        filename="dup.txt",
        status="pending",
        doc_metadata={"file_sha256": "sha-dup.txt", "pipeline_hash": "pipeline-hash"},
        dedup_key="sha-dup.txt:pipeline-hash",
    )

    class _DedupDiag:
        constraint_name = document_upload.DOCUMENT_DEDUP_CONSTRAINT_NAME

    class _DedupOrigError(Exception):
        def __init__(self) -> None:
            super().__init__(document_upload.DOCUMENT_DEDUP_CONSTRAINT_NAME)
            self.diag = _DedupDiag()

    class _ConflictDB:
        def __init__(self) -> None:
            self.commit_calls = 0
            self.rollback_calls = 0

        def add(self, _document) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            self.commit_calls += 1
            raise IntegrityError("insert", {}, _DedupOrigError())

        def rollback(self) -> None:
            self.rollback_calls += 1

        def refresh(self, _document) -> None:  # noqa: ANN001
            return None

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)

    duplicate_hits = {"count": 0}

    def _find_duplicate_document(*args, **kwargs):  # noqa: ANN001, ANN003
        duplicate_hits["count"] += 1
        if duplicate_hits["count"] == 1:
            return None
        return duplicate_document

    monkeypatch.setattr(documents_module, "_find_duplicate_document", _find_duplicate_document, raising=True)

    async def _schedule(**_kwargs) -> bool:  # noqa: ANN003, ANN202
        raise AssertionError("dedup conflict should return the winning document without requeueing")

    monkeypatch.setattr(document_upload, "_schedule_document_processing", _schedule, raising=True)

    db = _ConflictDB()
    result = await document_upload.upload_document(
        background_tasks=BackgroundTasks(),
        file=_make_upload("dup.txt"),
        form=document_upload.UploadDocumentFormFields(
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
            pipeline=None,
            dataset_id=dataset_id,
            user_metadata=None,
        ),
        overrides_form=_build_overrides_form(),
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert result.id == duplicate_document.id
    assert db.commit_calls == 1
    assert db.rollback_calls == 1
    assert duplicate_hits["count"] == 2


@pytest.mark.asyncio
async def test_precheck_staged_batch_hands_retry_ingest_lock_to_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dataset_id = uuid.uuid4()
    duplicate = SimpleNamespace(
        id=uuid.uuid4(),
        filename="batch.txt",
        status="completed",
        doc_metadata={},
    )
    released: list[tuple[str, str]] = []

    class _OuterDB:
        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    _patch_quota(monkeypatch)
    _patch_minimal_document_resolution(monkeypatch, dataset_id=dataset_id)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(document_upload.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module, "save_upload_file_with_hash", _fake_save_upload_file_with_hash, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_find_duplicate_document_by_sha",
        lambda *args, **kwargs: duplicate,
        raising=True,
    )
    monkeypatch.setattr(
        documents_module,
        "SessionLocal",
        lambda: SimpleNamespace(commit=lambda: None, refresh=lambda *_args: None, close=lambda: None),
        raising=True,
    )
    monkeypatch.setattr(documents_module, "run_dataset_precheck_scan", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(documents_module, "apply_ingestion_policy_suggestion", lambda *_args, **_kwargs: None, raising=True)

    async def _queue() -> object:
        return object()

    async def _acquire(redis, *, key: str, value: str, ttl_sec: int, fail_open: bool = True) -> bool:  # noqa: ANN001
        return True

    async def _release(redis, *, key: str, value: str) -> None:  # noqa: ANN001
        released.append((key, value))

    async def _retry(**_kwargs) -> None:  # noqa: ANN003
        meta = dict(duplicate.doc_metadata or {})
        meta["task_id"] = "task-1"
        duplicate.doc_metadata = meta

    monkeypatch.setattr("app.tasks.queue.get_queue", _queue, raising=False)
    monkeypatch.setattr("app.tasks.locks.acquire_lock", _acquire, raising=False)
    monkeypatch.setattr("app.tasks.locks.release_lock", _release, raising=False)
    monkeypatch.setattr(documents_module, "retry_document_processing", _retry, raising=True)

    result = await document_upload.upload_documents_batch(
        background_tasks=BackgroundTasks(),
        files=[_make_upload("batch.txt")],
        form=document_upload.UploadDocumentsBatchFormFields(
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
            pipeline=None,
            dataset_id=dataset_id,
            precheck_first=True,
            precheck_only=False,
            upload_only=False,
            user_metadata_map=None,
            max_concurrent=1,
        ),
        overrides_form=_build_overrides_form(),
        tenant_id=uuid.uuid4(),
        account_id="acct-1",
        db=_OuterDB(),
    )

    assert result["successful_count"] == 1
    assert released == []
    assert duplicate.doc_metadata["task_id"] == "task-1"
    assert duplicate.doc_metadata["ingest_lock_key"].startswith("lock:ingest:")
    assert duplicate.doc_metadata["ingest_lock_value"]
