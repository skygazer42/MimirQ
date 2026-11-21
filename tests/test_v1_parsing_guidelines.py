import asyncio
import io
import threading
from dataclasses import fields
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from pydantic.fields import FieldInfo

from app.api.schemas.pipelines import PipelineIngestionPreviewForm, PipelineParsePreviewForm
from app.api.v1.pipelines.parsing import ParsingDocumentUploadForm


def _document(tenant_id, dataset_id):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        file_path="minio://bucket/source.pdf",
        file_type="pdf",
        doc_metadata={},
        owner_id="owner",
        status="pending",
        processing_progress=0,
    )


def _form(model, **overrides):
    values = {
        field.name: field.default.default if isinstance(field.default, FieldInfo) else field.default
        for field in fields(model)
    }
    return model(**(values | overrides))


def _worker_sessions(monkeypatch, document=None):
    from app.services.runtime import retrieval_limiter as rag_runtime_limiter

    loop_thread = threading.get_ident()
    sessions = []

    class Session:
        def __enter__(self):
            assert threading.get_ident() == self.thread
            return self

        def __exit__(self, *_args):
            self.close()

        def __init__(self):
            assert threading.get_ident() != loop_thread
            self.thread = threading.get_ident()
            self.closed = False
            self.added = []
            sessions.append(self)

        def query(self, *args):
            assert threading.get_ident() == self.thread
            return self

        def filter(self, *args):
            return self

        def first(self):
            return document

        def get(self, *args):
            return document

        def add(self, item):
            assert threading.get_ident() == self.thread
            self.added.append(item)

        def commit(self):
            assert threading.get_ident() == self.thread

        def refresh(self, item):
            now = datetime.now(UTC)
            item.created_at = item.updated_at = now
            item.chunk_count = item.total_characters = 0
            item.processing_attempts = 0
            item.publication_status = "published"

        def close(self):
            assert threading.get_ident() == self.thread
            self.closed = True

    monkeypatch.setattr(rag_runtime_limiter, "SessionLocal", Session)
    from app.api.v1.pipelines import parsing

    monkeypatch.setattr(parsing, "SessionLocal", Session)
    return sessions


@pytest.mark.asyncio
async def test_workspace_source_filesystem_validation_runs_off_loop(monkeypatch, tmp_path):
    from app.api.v1.pipelines import parsing

    tenant_id = uuid4()
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")
    loop_thread = threading.get_ident()

    def validate(**kwargs):
        assert threading.get_ident() != loop_thread

    monkeypatch.setattr(parsing, "_assert_path_under_tenant_root", validate)
    result = await parsing._resolve_workspace_source_path(
        doc=SimpleNamespace(file_path=str(source)),
        tenant_id=tenant_id,
    )
    assert result == source


@pytest.mark.asyncio
async def test_workspace_parse_cleans_download_when_backend_validation_fails(monkeypatch, tmp_path):
    from app.api.v1.pipelines import parsing

    tenant_id, dataset_id = uuid4(), uuid4()
    document = _document(tenant_id, dataset_id)
    source = tmp_path / "download.pdf"
    source.write_bytes(b"pdf")
    _worker_sessions(monkeypatch, document)
    monkeypatch.setattr(parsing, "_get_workspace_document", lambda *a, **k: document)
    monkeypatch.setattr(parsing.dataset_service, "get_dataset", lambda *a: object())
    monkeypatch.setattr(parsing.dataset_service, "assert_dataset_writable", lambda *a: None)

    async def resolve(**kwargs):
        return source

    def invalid_backend(*_args, **kwargs):
        raise ValueError("unknown parser")

    monkeypatch.setattr(parsing, "_resolve_workspace_source_path", resolve)
    monkeypatch.setattr(parsing.parser_factory, "resolve_backend", invalid_backend)
    with pytest.raises(HTTPException) as error:
        await parsing.parse_workspace_document(
            document.id,
            SimpleNamespace(),
            parsing.ParsingDocumentParseQuery(parser_backend="basic"),
            tenant_id=tenant_id,
            account_id="owner",
        )
    assert error.value.status_code == 400
    assert not source.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["workspace", "document", "chunk"])
async def test_inline_previews_execute_parser_off_the_event_loop(monkeypatch, tmp_path, surface):
    from app.api.v1.documents import chunk_preview as document_chunk_preview
    from app.api.v1.documents import preview as document_preview
    from app.api.v1.pipelines import parsing

    loop_thread = threading.get_ident()
    tenant_id, dataset_id = uuid4(), uuid4()
    request = SimpleNamespace()
    expected = {"documents": [], "resolved_backend": "basic"}

    def inline(**kwargs):
        assert threading.get_ident() != loop_thread
        return expected

    if surface == "workspace":
        monkeypatch.setattr(parsing, "_should_inline_preview_parse", lambda _: True)
        monkeypatch.setattr(parsing, "_parse_inline_text_preview", inline)
        result = await parsing._parse_workspace_source(
            source_path=tmp_path / "source.txt",
            file_ext=".txt",
            request=request,
            tenant_id=tenant_id,
            account_id="owner",
            doc=_document(tenant_id, dataset_id),
            requested_backend="basic",
            resolved_backend="basic",
            image_caption_enabled=False,
            image_ocr_enabled=False,
        )
        assert result == expected
    elif surface == "document":
        monkeypatch.setattr(document_preview, "_should_inline_preview_parse", lambda _: True)
        monkeypatch.setattr(document_preview.parser_factory, "resolve_backend", lambda *a: "basic")
        monkeypatch.setattr(document_preview, "_parse_inline_text_preview", inline)
        result = await document_preview._parse_preview_payload(
            request=request,
            temp_path=tmp_path / "source.txt",
            tenant_id=tenant_id,
            account_id="owner",
            file_ext=".txt",
            parser_backend="basic",
        )
        assert result == expected
    else:

        def parse(*args, **kwargs):
            assert threading.get_ident() != loop_thread
            return [], "basic", {}

        monkeypatch.setattr(document_chunk_preview.settings, "PREVIEW_INLINE_TEXT_PARSE_ENABLED", True)
        monkeypatch.setattr(document_chunk_preview.parser_factory, "parse_with_provenance", parse)
        result = await document_chunk_preview._parse_uncached_preview_documents(
            temp_path=tmp_path / "source.txt",
            file_ext=".txt",
            tenant_id=tenant_id,
            account_id="owner",
            request=request,
            config=SimpleNamespace(parser_backend="basic"),
        )
        assert result[:2] == ([], "basic")


@pytest.mark.asyncio
async def test_workspace_object_download_cancellation_waits_then_removes_file(monkeypatch, tmp_path):
    from app.api.v1.pipelines import parsing

    tenant_id, dataset_id = uuid4(), uuid4()
    started, release, completed = threading.Event(), threading.Event(), threading.Event()
    destinations = []

    class Store:
        def stat_object(self, **kwargs):
            return None

        def download_object_to_path(self, *, destination, **kwargs):
            destinations.append(destination)
            started.set()
            assert release.wait(5)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"download complete")
            completed.set()

    monkeypatch.setattr(parsing.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        parsing, "resolve_document_object_reference", lambda *a, **k: (Store(), SimpleNamespace(object_name="key"))
    )
    task = asyncio.create_task(
        parsing._resolve_workspace_source_path(doc=_document(tenant_id, dataset_id), tenant_id=tenant_id)
    )
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await asyncio.to_thread(completed.wait, 5)
    assert destinations and not destinations[0].exists()


@pytest.mark.asyncio
async def test_workspace_upload_owns_worker_session_and_offloads_object_transfer(monkeypatch, tmp_path):
    from app.api.v1.pipelines import parsing
    from app.services.documents import source_persistence as document_source_persistence

    tenant_id, dataset_id = uuid4(), uuid4()
    loop_thread = threading.get_ident()
    sessions = _worker_sessions(monkeypatch)

    def ensure(db, *args):
        assert db in sessions and threading.get_ident() == db.thread

    class Store:
        def upload_document_file(self, **kwargs):
            assert threading.get_ident() != loop_thread
            assert kwargs["file_path"].read_bytes() == b"source"
            return "minio://bucket/source.txt"

    monkeypatch.setattr(parsing.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(parsing.dataset_service, "ensure_member", ensure)
    monkeypatch.setattr(
        parsing.dataset_service, "get_dataset", lambda *a: SimpleNamespace(id=dataset_id, name="Knowledge")
    )
    monkeypatch.setattr(parsing.dataset_service, "assert_dataset_writable", ensure)
    monkeypatch.setattr(parsing, "document_object_storage_enabled", lambda: True)
    monkeypatch.setattr(parsing, "get_document_object_store", Store)
    monkeypatch.setattr(document_source_persistence, "get_document_object_store", Store)
    monkeypatch.setattr(parsing, "document_object_store_metadata", lambda _: {})
    result = await parsing.upload_parsing_document(
        ParsingDocumentUploadForm(
            file=UploadFile(filename="source.txt", file=io.BytesIO(b"source")), dataset_id=dataset_id
        ),
        tenant_id=tenant_id,
        account_id="owner",
    )
    assert result.dataset_id == dataset_id
    assert sessions and all(session.closed for session in sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["document", "chunk"])
async def test_upload_previews_resolve_membership_and_metadata_in_worker(monkeypatch, tmp_path, surface):
    from app.api.v1.documents import chunk_preview as document_chunk_preview
    from app.api.v1.documents import preview as document_preview

    tenant_id, dataset_id = uuid4(), uuid4()
    sessions = _worker_sessions(monkeypatch)

    def ensure(db, *args):
        assert db in sessions and threading.get_ident() == db.thread

    async def disconnected():
        return False

    module = document_preview if surface == "document" else document_chunk_preview
    monkeypatch.setattr(module.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(module.dataset_service, "ensure_member", ensure)
    monkeypatch.setattr(module.dataset_service, "get_dataset", lambda *a: SimpleNamespace(dataset_metadata={}))
    monkeypatch.setattr(module.dataset_service, "assert_dataset_readable", ensure)
    if surface == "document":

        async def parse(**kwargs):
            return {"documents": [], "resolved_backend": "basic"}

        monkeypatch.setattr(module, "_parse_preview_payload", parse)
        result = await module.preview_document(
            SimpleNamespace(is_disconnected=disconnected),
            UploadFile(filename="source.txt", file=io.BytesIO(b"source")),
            _form(module.PreviewDocumentFormFields, dataset_id=str(dataset_id)),
            _form(module.PreviewDocumentGovernanceOverridesFormFields),
            tenant_id=tenant_id,
            account_id="owner",
            db=object(),
        )
        assert result.filename == "source.txt"
    else:

        async def run(**kwargs):
            # Exercise the metadata stage before stopping the expensive chunk pipeline.
            return "preview"

        monkeypatch.setattr(module, "_build_uploaded_preview_execution_state", run)
        monkeypatch.setattr(module, "_build_chunk_preview_response", lambda **kwargs: "preview")
        result = await module._execute_preview_chunking(
            request=SimpleNamespace(is_disconnected=disconnected),
            response=SimpleNamespace(),
            file=UploadFile(filename="source.txt", file=io.BytesIO(b"source")),
            params=_form(module.ChunkPreviewRequestFields, dataset_id=str(dataset_id)),
            db=object(),
            tenant_id=tenant_id,
            account_id="owner",
        )
        assert result == "preview"
    assert sessions and all(session.closed for session in sessions)
    assert not list(tmp_path.rglob("*.txt"))


@pytest.mark.asyncio
async def test_workspace_postprocessing_runs_off_loop_and_persists_in_worker(monkeypatch, tmp_path):
    from app.api.v1.pipelines import parsing

    tenant_id, dataset_id = uuid4(), uuid4()
    document = _document(tenant_id, dataset_id)
    document.status = "processing"
    document.processing_attempts = 1
    loop_thread = threading.get_ident()
    sessions = _worker_sessions(monkeypatch, document)

    async def parse(**kwargs):
        return {
            "documents": [{"page_content": "text", "metadata": {}}],
            "resolved_backend": "basic",
            "provenance": {"requested_backend": "basic", "resolved_backend": "basic"},
            "pdf_quality": None,
        }

    async def fallbacks(**kwargs):
        return "basic", kwargs["gate"], kwargs["artifact_docs"], "text", "text", None, []

    def vlm(**kwargs):
        assert threading.get_ident() != loop_thread
        return "text", kwargs["gate"], None, False

    def persist(*, db, **kwargs):
        assert db in sessions and threading.get_ident() == db.thread
        return "persisted"

    monkeypatch.setattr(parsing, "_parse_workspace_source", parse)
    monkeypatch.setattr(parsing, "_run_workspace_pdf_fallbacks", fallbacks)
    monkeypatch.setattr(parsing, "_apply_workspace_vlm_correction", vlm)
    monkeypatch.setattr(parsing, "_get_workspace_document", lambda *a, **k: document)
    monkeypatch.setattr(parsing, "_persist_workspace_parse_result", persist)
    result = await parsing._execute_workspace_parse_request(
        doc=document,
        request=SimpleNamespace(),
        tenant_id=tenant_id,
        account_id="owner",
        source_path=tmp_path / "source.txt",
        parse_attempt=1,
        requested_backend="basic",
        resolved_backend="basic",
        file_ext=".txt",
        image_caption_enabled=False,
        image_ocr_enabled=False,
        vlm_correction_enabled=False,
    )
    assert result == "persisted"
    assert all(session.closed for session in sessions)


@pytest.mark.asyncio
async def test_pipeline_parse_preview_uses_worker_database_and_original_request_loop(monkeypatch, tmp_path):
    from app.api.v1.pipelines import routes as pipeline

    tenant_id = uuid4()
    sessions = _worker_sessions(monkeypatch)
    loop = asyncio.get_running_loop()

    def ensure(db, *args):
        assert db in sessions and threading.get_ident() == db.thread

    async def disconnected():
        assert asyncio.get_running_loop() is loop
        return False

    async def parse(*, disconnect_check, **kwargs):
        assert not await disconnect_check()
        return {"markdown": "preview"}

    monkeypatch.setattr(pipeline.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline.dataset_service, "ensure_member", ensure)
    monkeypatch.setattr(pipeline, "run_subprocess_worker", parse)
    result = await pipeline.parse_preview(
        SimpleNamespace(is_disconnected=disconnected),
        PipelineParsePreviewForm(file=UploadFile(filename="source.txt", file=io.BytesIO(b"source"))),
        tenant_id=tenant_id,
        account_id="owner",
    )
    assert result == {"markdown": "preview"}
    assert sessions and all(session.closed for session in sessions)
    assert not list(tmp_path.rglob("*.txt"))


@pytest.mark.asyncio
async def test_pipeline_ingestion_preview_uses_cleaning_owner_and_offloads_preprocess(monkeypatch, tmp_path):
    from app.api.schemas.sources.policy import IngestionPolicy, IngestionRule
    from app.api.v1.pipelines import routes as pipeline

    tenant_id, dataset_id = uuid4(), uuid4()
    loop_thread = threading.get_ident()
    sessions = _worker_sessions(monkeypatch)

    def ensure(db, *args):
        assert db in sessions and threading.get_ident() == db.thread

    def preprocess(path, steps):
        assert threading.get_ident() != loop_thread
        return path, {"changed": False, "size_before": 6, "size_after": 6, "steps": [], "warnings": []}

    async def disconnected():
        return False

    async def parse(**kwargs):
        return {"markdown": "preview", "documents": [], "backend": "basic"}

    def route_called(**kwargs):
        raise AssertionError("ingestion must call the cleaning owner")

    rule = IngestionRule(id="rule", name="Rule")
    monkeypatch.setattr(pipeline.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline.dataset_service, "ensure_member", ensure)
    monkeypatch.setattr(pipeline.dataset_service, "get_dataset", lambda *a: SimpleNamespace(dataset_metadata={}))
    monkeypatch.setattr(pipeline.dataset_service, "assert_dataset_readable", ensure)
    monkeypatch.setattr(pipeline, "parse_ingestion_policy_from_metadata", lambda _: IngestionPolicy(rules=[rule]))
    monkeypatch.setattr(pipeline, "match_ingestion_rule", lambda *a, **k: rule)
    monkeypatch.setattr(pipeline, "_preprocess_ingestion_preview_file", preprocess)
    monkeypatch.setattr(pipeline, "run_subprocess_worker", parse)
    monkeypatch.setattr(pipeline, "clean_preview", route_called)
    result = await pipeline.ingestion_preview(
        SimpleNamespace(is_disconnected=disconnected),
        PipelineIngestionPreviewForm(
            file=UploadFile(filename="source.txt", file=io.BytesIO(b"source")), dataset_id=dataset_id
        ),
        tenant_id=tenant_id,
        account_id="owner",
    )
    assert result["clean"].markdown == "preview"
    assert sessions and all(session.closed for session in sessions)


@pytest.mark.asyncio
async def test_auto_annotation_cpu_provider_runs_off_loop(monkeypatch):
    from app.api.schemas.pipelines.preview import AutoAnnotationRequest
    from app.api.v1.pipelines.support import auto_annotations

    loop_thread = threading.get_ident()

    def cpu(*args, **kwargs):
        assert threading.get_ident() != loop_thread

    monkeypatch.setattr(auto_annotations, "_collect_cpu_auto_provider", cpu)
    monkeypatch.setattr(auto_annotations, "_collect_document_focus_rule_fallback", lambda *a: None)
    await auto_annotations._collect_document_focus_annotations(
        auto_annotations._AutoAnnotationDraft(),
        "text",
        AutoAnnotationRequest(text="text"),
        {"cpu"},
        5,
    )


@pytest.mark.asyncio
async def test_cancelled_workspace_upload_removes_uploaded_object_before_persistence(monkeypatch, tmp_path):
    from app.api.v1.pipelines import parsing
    from app.services.documents import source_persistence as document_source_persistence

    tenant_id, dataset_id = uuid4(), uuid4()
    sessions = _worker_sessions(monkeypatch)
    started, release = threading.Event(), threading.Event()
    removed = []

    class Store:
        def upload_document_file(self, **kwargs):
            started.set()
            assert release.wait(5)
            return "minio://bucket/source.txt"

    async def cleanup(*, store, reference):
        removed.append(reference.object_name)

    store = Store()
    monkeypatch.setattr(parsing.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(parsing.dataset_service, "ensure_member", lambda *a: None)
    monkeypatch.setattr(
        parsing.dataset_service, "get_dataset", lambda *a: SimpleNamespace(id=dataset_id, name="Knowledge")
    )
    monkeypatch.setattr(parsing.dataset_service, "assert_dataset_writable", lambda *a: None)
    monkeypatch.setattr(parsing, "document_object_storage_enabled", lambda: True)
    monkeypatch.setattr(parsing, "get_document_object_store", lambda: store)
    monkeypatch.setattr(parsing, "document_object_store_metadata", lambda _: {})
    monkeypatch.setattr(document_source_persistence, "get_document_object_store", lambda: store)
    monkeypatch.setattr(document_source_persistence, "_cleanup_unpersisted_store_object", cleanup)
    task = asyncio.create_task(
        parsing.upload_parsing_document(
            ParsingDocumentUploadForm(
                file=UploadFile(filename="source.txt", file=io.BytesIO(b"source")), dataset_id=dataset_id
            ),
            tenant_id=tenant_id,
            account_id="owner",
        )
    )
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert removed == ["source.txt"]
    assert all(not session.added for session in sessions)
    assert not list(tmp_path.rglob("*.txt"))
