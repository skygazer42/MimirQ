"""The dispatch service must work without loading a document route assembler."""

import asyncio
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks

from app.services.documents import processing_dispatch as dispatch


class DispatchDB:
    def __init__(self, document=None):
        self.document = document

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def query(self, *_models):
        return self

    def filter(self, *_conditions):
        return self

    def first(self):
        return self.document

    def commit(self) -> None:
        pass

    def refresh(self, document) -> None:
        pass


def _retry_plan(document, source):
    return dispatch.RetryDocumentPlan(
        document_id=document.id,
        source=source,
        pipeline_hash="pipeline-a",
        file_type=document.file_type,
        parser_backend=document.doc_metadata.get("parser_backend"),
        chunk_strategy=document.doc_metadata.get("chunk_strategy"),
    )


@pytest.mark.asyncio
async def test_retry_queue_handoff_never_downloads_a_stored_source(monkeypatch):
    class Store:
        def download_object_to_path(self, **kwargs):
            pytest.fail("Accepted queue jobs must read their own stored source")

    document = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), file_type="txt", doc_metadata={}, status="pending", processing_progress=0
    )
    background_tasks = BackgroundTasks()
    queued = []

    async def enqueue(**kwargs):
        queued.append(kwargs)
        return "accepted-job"

    monkeypatch.setattr(dispatch, "enqueue_document_processing", enqueue)
    monkeypatch.setattr(dispatch, "SessionLocal", lambda: DispatchDB(document))
    await dispatch.dispatch_retry_document(
        plan=_retry_plan(
            document,
            dispatch.StoredProcessingSource(uri="s3://bucket/source.txt", store=Store(), object_name="source.txt"),
        ),
        background_tasks=background_tasks,
        tenant_id=document.tenant_id,
        requested_by="editor",
    )
    assert document.doc_metadata["task_id"] == "accepted-job"
    assert queued[0]["job_id"] == f"doc:{document.tenant_id}:{document.id}:pipeline-a"
    assert background_tasks.tasks == []


@pytest.mark.asyncio
async def test_upload_optional_queue_error_falls_back_to_local_work(monkeypatch, tmp_path: Path):
    source = tmp_path / "upload.txt"
    source.write_text("content", encoding="utf-8")
    document = SimpleNamespace(id=uuid4(), file_path="s3://bucket/upload.txt", doc_metadata={})
    background_tasks, processed = BackgroundTasks(), []

    async def enqueue(**kwargs):
        raise RuntimeError("queue offline")

    async def process(file_path, *args, **kwargs):
        processed.append(file_path)

    monkeypatch.setattr(dispatch.settings, "TASK_QUEUE_ENABLED", False)
    monkeypatch.setattr(dispatch, "enqueue_document_processing", enqueue)
    monkeypatch.setattr(dispatch, "run_document_processing_limited", process)
    keep_local = await dispatch.dispatch_uploaded_document(
        source=dispatch.LocalProcessingSource(source),
        background_tasks=background_tasks,
        db=DispatchDB(),
        document=document,
        tenant_id=uuid4(),
        requested_by="editor",
        pipeline_hash="pipeline-a",
        parser_backend="auto",
        chunk_strategy="langchain_recursive",
    )
    assert keep_local is True
    assert source.exists()
    await background_tasks()
    assert processed == [source]
    assert not source.exists()


@pytest.mark.asyncio
async def test_retry_optional_queue_exception_remains_a_failure(monkeypatch, tmp_path: Path):
    error = RuntimeError("queue offline")

    async def enqueue(**kwargs):
        raise error

    monkeypatch.setattr(dispatch.settings, "TASK_QUEUE_ENABLED", False)
    monkeypatch.setattr(dispatch, "enqueue_document_processing", enqueue)
    background_tasks = BackgroundTasks()
    with pytest.raises(RuntimeError) as caught:
        await dispatch.dispatch_retry_document(
            plan=_retry_plan(
                SimpleNamespace(id=uuid4(), file_type="txt", doc_metadata={}),
                dispatch.LocalProcessingSource(tmp_path / "retry.txt"),
            ),
            background_tasks=background_tasks,
            tenant_id=uuid4(),
            requested_by="editor",
        )
    assert caught.value is error
    assert background_tasks.tasks == []


@pytest.mark.asyncio
async def test_retry_waits_for_stored_download_before_cancellation_cleans_its_temp(monkeypatch, tmp_path: Path):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    downloaded = []

    class Store:
        def download_object_to_path(self, *, destination, **kwargs):
            started.set()
            assert release.wait(timeout=3)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("downloaded", encoding="utf-8")
            downloaded.append(destination)
            finished.set()

    async def no_queue(**kwargs):
        return None

    monkeypatch.setattr(dispatch.settings, "TASK_QUEUE_ENABLED", False)
    monkeypatch.setattr(dispatch.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(dispatch, "enqueue_document_processing", no_queue)
    document = SimpleNamespace(id=uuid4(), file_type="txt", doc_metadata={})
    background_tasks = BackgroundTasks()
    await dispatch.dispatch_retry_document(
        plan=_retry_plan(document, dispatch.StoredProcessingSource("s3://bucket/source.txt", Store(), "source.txt")),
        background_tasks=background_tasks,
        tenant_id=uuid4(),
        requested_by="editor",
    )
    task = asyncio.create_task(background_tasks())
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    await asyncio.sleep(0.05)
    still_running = not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await asyncio.to_thread(finished.wait, 1)
    assert still_running, "Cancellation must not abandon a downloader that still owns the temp file"
    assert len(downloaded) == 1
    assert not downloaded[0].exists()


def test_processing_service_imports_and_executes_with_the_route_assembler_blocked():
    code = """
import asyncio
import importlib.abc
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

class NoDocumentAssembler(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.api.v1.documents.routes':
            raise AssertionError("business operation reads its route assembler")
sys.meta_path.insert(0, NoDocumentAssembler())

from fastapi import BackgroundTasks
from app.models.documents.records import Document
from app.services.documents import processing_dispatch as dispatch
from app.services.documents import processing as operations

async def accepted(**kwargs):
    return "accepted-job"
dispatch.enqueue_document_processing = accepted
operations.dataset_service.ensure_member = lambda *args, **kwargs: None
operations.assert_document_writable_for_lifecycle = lambda *args, **kwargs: None
operations.assert_document_readable_for_lifecycle = lambda *args, **kwargs: None
operations.reconcile_document_index_channels = lambda *args, **kwargs: None

class DB:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def query(self, model): return self
    def filter(self, *args): return self
    def first(self): return document
    def commit(self): pass
    def refresh(self, row): pass

operations.SessionLocal = DB
dispatch.SessionLocal = DB

with TemporaryDirectory() as directory:
    source = Path(directory) / "source.txt"
    source.write_text("content", encoding="utf-8")
    document = Document(id=uuid4(), tenant_id=uuid4(), file_path=str(source),
        filename="source.txt", file_type="txt", status="failed", processing_progress=0,
        processing_attempts=2, doc_metadata={"parser_backend":"auto"})
    result = asyncio.run(operations.retry_document(document_id=document.id,
        background_tasks=BackgroundTasks(), tenant_id=document.tenant_id,
        account_id="owner", db=DB()))
    assert result.status == "pending" and document.doc_metadata["task_id"] == "accepted-job"
    assert operations.read_document_status(document_id=document.id,
        tenant_id=document.tenant_id, account_id="owner", db=DB()).id == document.id
assert 'app.api.v1.documents.routes' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
