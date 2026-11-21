import asyncio
import threading
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.documents import source_persistence as persistence
from app.services.documents.source_persistence import find_duplicate_document, find_duplicate_document_by_sha


@pytest.mark.parametrize("operation", [find_duplicate_document, find_duplicate_document_by_sha])
def test_dedup_database_failure_is_not_reported_as_no_duplicate(operation):
    error = RuntimeError("authoritative database unavailable")

    class Query:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def first(self):
            raise error

        def limit(self, count):
            return self

        def all(self):
            return []

    class DB:
        def query(self, *args):
            return Query()

    kwargs = {"tenant_id": uuid4(), "dataset_id": uuid4(), "file_sha256": "sha-a"}
    if operation is find_duplicate_document:
        kwargs["pipeline_hash"] = "pipeline-a"
    with pytest.raises(RuntimeError) as caught:
        operation(DB(), **kwargs)
    assert caught.value is error


@pytest.mark.asyncio
async def test_cancelled_source_upload_waits_for_the_writer_and_removes_its_unpersisted_object(
    monkeypatch, tmp_path: Path
):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")
    deleted = []

    class Store:
        def upload_document_file(self, *, file_path, **kwargs):
            started.set()
            assert release.wait(timeout=3)
            assert file_path.exists(), "The writer still owns its source until it finishes"
            finished.set()
            return "s3://bucket/source.txt"

        def delete_object(self, *, object_name):
            deleted.append(object_name)

    store = Store()
    monkeypatch.setattr(persistence, "get_document_object_store", lambda: store)
    monkeypatch.setattr(persistence, "object_store_backend_config", lambda value: {"bucket": "bucket"})
    task = asyncio.create_task(
        persistence.store_document_source(
            file_path=source,
            tenant_id=uuid4(),
            dataset_id=uuid4(),
            document_id=uuid4(),
            extension=".txt",
            content_type="text/plain",
        )
    )
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    await asyncio.sleep(0.05)
    waiting_for_writer = not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await asyncio.to_thread(finished.wait, 1)
    assert waiting_for_writer, "Cancelling the request must not abandon the source writer"
    assert deleted == ["source.txt"]
    assert not source.exists()
