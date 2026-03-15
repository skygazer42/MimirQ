from __future__ import annotations

import uuid

import pytest

from tests.helpers.async_utils import yield_control


class _DummyQuery:
    def __init__(self, run):  # noqa: ANN001
        self._run = run

    def options(self, *_a, **_k):  # noqa: ANN001
        return self

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN201
        return self._run


class _DummyDB:
    def __init__(self, run):  # noqa: ANN001
        self._run = run
        self.commits = 0

    def query(self, *_a, **_k):  # noqa: ANN001
        return _DummyQuery(self._run)

    def add(self, obj) -> None:  # noqa: ANN001
        # Keep a minimal in-memory "run.documents" view for idempotency checks.
        try:
            from app.models.connector import ConnectorRunDocument

            if isinstance(obj, ConnectorRunDocument):
                self._run.documents.append(obj)
        except Exception:
            pass

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_execute_url_batch_run_resumes_from_cursor_and_skips_processed(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.models.connector import ConnectorRunDocument

    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Run:
        def __init__(self) -> None:
            self.id = run_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.connector_id = "url_batch"
            self.requested_by = "tester"
            self.status = "pending"
            self.config = {"urls": ["https://example.com/1", "https://example.com/2", "https://example.com/3"]}
            # Pretend we already finished URL[0].
            self.stats = {"cursor": 1, "processed_urls": 1, "created": 1, "failed": 0, "document_ids": ["doc-1"]}
            self.error_message = None
            self.started_at = None
            self.finished_at = None
            self.documents = [
                ConnectorRunDocument(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    document_id=uuid.uuid4(),
                    source_ref="https://example.com/1",
                    status="created",
                )
            ]

    run = _Run()
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors_module, "SessionLocal", lambda: dummy_db, raising=True)

    # Avoid touching real permission tables in this unit test.
    monkeypatch.setattr(connectors_module.DocumentPermissionService, "update_partial_member_list", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors_module.DocumentPermissionService, "clear_partial_member_list", lambda *_a, **_k: None, raising=True)

    ingested_urls: list[str] = []

    class _Doc:
        def __init__(self) -> None:
            self.id = uuid.uuid4()
            self.access_mode = None
            self.owner_id = ""

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        await yield_control()
        ingested_urls.append(str(getattr(body, "url", "")))
        return _Doc()

    monkeypatch.setattr(connectors_module, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)

    await connectors_module._execute_url_batch_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == ["https://example.com/2", "https://example.com/3"]
    assert int((run.stats or {}).get("cursor") or 0) == 3
    assert int((run.stats or {}).get("processed_urls") or 0) == 3

