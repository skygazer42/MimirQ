from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_ingest_local_html_request_creates_doc_and_processes_inline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import app.api.v1.documents as documents_module
    from app.core.config import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self, dataset_id0: uuid.UUID):  # noqa: ANN001
            self.id = dataset_id0
            self.dataset_metadata = {}

    monkeypatch.setattr(
        documents_module,
        "_resolve_writable_dataset",
        lambda *_a, **_k: _Dataset(dataset_id),
        raising=True,
    )

    async def _fake_enqueue_document_processing(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        await yield_control()
        return None

    async def _fake_process_document(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        await yield_control()
        return None

    monkeypatch.setattr(documents_module, "enqueue_document_processing", _fake_enqueue_document_processing, raising=True)
    monkeypatch.setattr(documents_module.document_processor, "process_document", _fake_process_document, raising=True)

    class _DummyDB:
        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    body = documents_module.LocalHtmlIngestRequest(
        html="<p>Hello</p>",
        source_url="https://example.atlassian.net/wiki/spaces/DOCS/pages/123/Hello",
        dataset_id=dataset_id,
        filename="123-Hello.html",
        parser_backend="auto",
        chunk_strategy="langchain_recursive",
        pipeline=None,
    )

    doc = await documents_module._ingest_local_html_request(
        background_tasks=None,
        body=body,
        tenant_id=tenant_id,
        account_id="test-account",
        db=_DummyDB(),
        ingestion_kind="test_local_html",
    )

    assert str(getattr(doc, "file_type", "")) == "html"
    meta = getattr(doc, "doc_metadata", None) or {}
    assert meta.get("source_url") == body.source_url
    assert meta.get("pipeline_hash")

    file_path = Path(str(getattr(doc, "file_path", "")))
    assert file_path.exists()


@pytest.mark.asyncio
async def test_run_document_processing_limited_serializes_when_queue_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.documents as documents_module
    from app.core.config import settings

    monkeypatch.setattr(settings, "API_DOCUMENT_BACKGROUND_MAX_CONCURRENCY", 1, raising=False)
    documents_module._background_processing_semaphores.clear()

    active = 0
    max_active = 0

    async def _fake_process_document(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"status": "success"}

    monkeypatch.setattr(documents_module.document_processor, "process_document", _fake_process_document, raising=True)

    await asyncio.gather(
        documents_module.run_document_processing_limited(Path("a"), uuid.uuid4(), uuid.uuid4()),
        documents_module.run_document_processing_limited(Path("b"), uuid.uuid4(), uuid.uuid4()),
        documents_module.run_document_processing_limited(Path("c"), uuid.uuid4(), uuid.uuid4()),
    )

    assert max_active == 1
