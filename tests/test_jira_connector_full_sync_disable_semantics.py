from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from tests.test_connector_saved_state_resume import _import_connectors_with_lightweight_stubs


def _make_run(*, config: dict):  # noqa: ANN202
    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Run:
        def __init__(self) -> None:
            self.id = run_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.connector_id = "jira_project"
            self.requested_by = "tester"
            self.status = "pending"
            self.config = dict(config)
            self.stats: dict[str, object] = {}
            self.error_message = None
            self.task_id = None
            self.started_at = None
            self.finished_at = None
            self.documents: list[object] = []

    return _Run(), run_id, tenant_id


class _RunQuery:
    def __init__(self, run):  # noqa: ANN001
        self._run = run

    def options(self, *_a, **_k):  # noqa: ANN001
        return self

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN201
        return self._run


class _RunDB:
    def __init__(self, run):  # noqa: ANN001
        self._run = run

    def query(self, _model):  # noqa: ANN001
        return _RunQuery(self._run)

    def add(self, obj) -> None:  # noqa: ANN001
        self._run.documents.append(obj)

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class _CreatedDoc:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.doc_metadata: dict[str, object] = {}
        self.access_mode = None
        self.owner_id = None


class _FakePool:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self._payloads = list(payloads)

    async def request_with_retry(self, method: str, url: str, **_kwargs):  # noqa: ANN201
        if not url.endswith("/rest/api/3/search"):
            raise AssertionError(f"unexpected jira url: {url}")
        payload = self._payloads.pop(0) if self._payloads else {"issues": []}
        return httpx.Response(200, json=payload, request=httpx.Request(method, url))


def _jira_issue(issue_id: str, issue_key: str, updated: str) -> dict[str, object]:
    return {
        "id": issue_id,
        "key": issue_key,
        "fields": {
            "summary": f"Summary for {issue_key}",
            "description": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": f"Description for {issue_key}"}]}],
            },
            "updated": updated,
            "issuetype": {"name": "Task"},
            "priority": {"name": "Medium"},
            "status": {"name": "To Do"},
            "labels": [],
            "comment": {"comments": []},
        },
        "renderedFields": {
            "description": f"<p>Description for {issue_key}</p>",
            "comment": {"comments": []},
        },
    }


async def _fake_ingest_local_html_request(*_a, **_k):  # noqa: ANN001, ANN202
    return _CreatedDoc()


@pytest.mark.asyncio
async def test_execute_jira_project_run_reconciles_missing_issues_after_complete_full_sync(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        config={
            "base_url": "https://example.atlassian.net",
            "project_key": "PLAT",
            "sync_mode": "full",
            "max_issues": 10,
            "page_size": 2,
            "include_comments": False,
        }
    )
    dummy_db = _RunDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        connectors,
        "_ingest_local_html_request",
        _fake_ingest_local_html_request,
        raising=True,
    )

    issue = _jira_issue("10000", "PLAT-1", "2026-03-07T01:02:03.000+0000")
    monkeypatch.setattr(
        connectors,
        "get_http_client_pool",
        lambda: _FakePool([{"startAt": 0, "maxResults": 2, "total": 1, "issues": [issue]}]),
        raising=True,
    )

    seen: dict[str, object] = {}

    def _reconcile_stub(_db, **kwargs):  # noqa: ANN001
        seen["kwargs"] = kwargs
        return 1, 3

    monkeypatch.setattr(
        connectors,
        "_soft_disable_jira_documents_missing_from_full_sync",
        _reconcile_stub,
        raising=False,
    )

    await connectors._execute_jira_project_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert run.status == "completed"
    assert (seen.get("kwargs") or {}).get("base_url") == "https://example.atlassian.net"
    assert (seen.get("kwargs") or {}).get("project_key") == "PLAT"
    assert (seen.get("kwargs") or {}).get("seen_issue_urls") == {
        "https://example.atlassian.net/browse/PLAT-1"
    }
    assert int((run.stats or {}).get("removed_issues_reconciled") or 0) == 1
    assert int((run.stats or {}).get("removed_documents_disabled") or 0) == 3


@pytest.mark.asyncio
async def test_execute_jira_project_run_skips_reconciliation_when_full_sync_listing_is_incomplete(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        config={
            "base_url": "https://example.atlassian.net",
            "project_key": "PLAT",
            "sync_mode": "full",
            "max_issues": 1,
            "page_size": 1,
            "include_comments": False,
        }
    )
    dummy_db = _RunDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        connectors,
        "_ingest_local_html_request",
        _fake_ingest_local_html_request,
        raising=True,
    )

    issue = _jira_issue("10000", "PLAT-1", "2026-03-07T01:02:03.000+0000")
    monkeypatch.setattr(
        connectors,
        "get_http_client_pool",
        lambda: _FakePool([{"startAt": 0, "maxResults": 1, "total": 2, "issues": [issue]}]),
        raising=True,
    )

    calls: list[dict[str, object]] = []

    def _reconcile_stub(_db, **kwargs):  # noqa: ANN001
        calls.append(dict(kwargs))
        return 2, 4

    monkeypatch.setattr(
        connectors,
        "_soft_disable_jira_documents_missing_from_full_sync",
        _reconcile_stub,
        raising=False,
    )

    await connectors._execute_jira_project_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert run.status == "completed"
    assert calls == []
    assert int((run.stats or {}).get("removed_issues_reconciled") or 0) == 0
    assert int((run.stats or {}).get("removed_documents_disabled") or 0) == 0


@pytest.mark.asyncio
async def test_execute_jira_project_run_does_not_reconcile_missing_issues_during_incremental_sync(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        config={
            "base_url": "https://example.atlassian.net",
            "project_key": "PLAT",
            "sync_mode": "incremental",
            "max_issues": 5,
            "page_size": 2,
            "include_comments": False,
            "_state": {"last_modified": "2026-03-06T00:00:00.000+0000"},
        }
    )
    dummy_db = _RunDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        connectors,
        "_ingest_local_html_request",
        _fake_ingest_local_html_request,
        raising=True,
    )

    issue = _jira_issue("10001", "PLAT-2", "2026-03-07T04:05:06.000+0000")
    monkeypatch.setattr(
        connectors,
        "get_http_client_pool",
        lambda: _FakePool([{"startAt": 0, "maxResults": 2, "total": 1, "issues": [issue]}]),
        raising=True,
    )

    calls: list[dict[str, object]] = []

    def _reconcile_stub(_db, **kwargs):  # noqa: ANN001
        calls.append(dict(kwargs))
        return 1, 1

    monkeypatch.setattr(
        connectors,
        "_soft_disable_jira_documents_missing_from_full_sync",
        _reconcile_stub,
        raising=False,
    )

    await connectors._execute_jira_project_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert run.status == "completed"
    assert calls == []
    assert int((run.stats or {}).get("removed_issues_reconciled") or 0) == 0
    assert int((run.stats or {}).get("removed_documents_disabled") or 0) == 0


@pytest.mark.asyncio
async def test_execute_jira_project_run_reconciles_missing_attachments_during_incremental_sync(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        config={
            "base_url": "https://example.atlassian.net",
            "project_key": "PLAT",
            "sync_mode": "incremental",
            "_state": {"last_modified": "2026-03-06T00:00:00.000+0000"},
            "max_issues": 10,
            "page_size": 2,
            "include_comments": False,
            "include_attachments": True,
            "max_attachments_per_issue": 5,
            "max_total_attachments": 20,
        }
    )
    dummy_db = _RunDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        connectors,
        "_ingest_local_html_request",
        _fake_ingest_local_html_request,
        raising=True,
    )

    issue = _jira_issue("10001", "PLAT-2", "2026-03-07T04:05:06.000+0000")
    issue_fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    issue_fields["attachment"] = []

    monkeypatch.setattr(
        connectors,
        "get_http_client_pool",
        lambda: _FakePool(
            [
                {"startAt": 0, "maxResults": 1, "total": 1, "issues": [issue]},
                {"startAt": 1, "maxResults": 1, "total": 1, "issues": []},
            ]
        ),
        raising=True,
    )

    calls: list[dict[str, object]] = []

    def _attachment_reconcile_stub(_db, **kwargs):  # noqa: ANN001
        calls.append(dict(kwargs))
        return 1

    monkeypatch.setattr(
        connectors,
        "_soft_disable_jira_attachment_documents_missing_from_issue",
        _attachment_reconcile_stub,
        raising=False,
    )

    await connectors._execute_jira_project_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert run.status == "completed"
    assert len(calls) == 1
    assert calls[0].get("issue_url") == "https://example.atlassian.net/browse/PLAT-2"
    assert calls[0].get("seen_attachment_urls") == set()
    assert int((run.stats or {}).get("removed_attachment_documents_disabled") or 0) == 1


@pytest.mark.asyncio
async def test_execute_jira_project_run_replays_boundary_timestamp_and_skips_seen_issue_ids(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        config={
            "base_url": "https://example.atlassian.net",
            "project_key": "PLAT",
            "sync_mode": "incremental",
            "max_issues": 5,
            "page_size": 5,
            "include_comments": False,
            "_state": {
                "last_modified": "2026-03-06T00:00:00.000+0000",
                "last_modified_ids": ["10000"],
            },
        }
    )
    dummy_db = _RunDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    seen: dict[str, object] = {"created_issue_keys": []}

    async def _fake_ingest_local_html_request(*_a, **_k):  # noqa: ANN001, ANN202
        body = _k.get("body")
        source_url = getattr(body, "source_url", None)
        if source_url and source_url.endswith("/PLAT-1"):
            seen.setdefault("created_issue_keys", []).append("PLAT-1")
        if source_url and source_url.endswith("/PLAT-2"):
            seen.setdefault("created_issue_keys", []).append("PLAT-2")
        return _CreatedDoc()

    monkeypatch.setattr(connectors, "_ingest_local_html_request", _fake_ingest_local_html_request, raising=True)

    class _RecordingPool:
        def __init__(self) -> None:
            self.jqls: list[str] = []

        async def request_with_retry(self, method: str, url: str, **kwargs):  # noqa: ANN201
            if not url.endswith("/rest/api/3/search"):
                raise AssertionError(f"unexpected jira url: {url}")
            params = kwargs.get("params") or {}
            self.jqls.append(str(params.get("jql") or ""))
            start_at = int(params.get("startAt", 0) or 0)
            if start_at > 0:
                payload = {"startAt": start_at, "maxResults": 5, "total": 2, "issues": []}
                return httpx.Response(200, json=payload, request=httpx.Request(method, url))
            payload = {
                "startAt": 0,
                "maxResults": 5,
                "total": 2,
                "issues": [
                    _jira_issue("10000", "PLAT-1", "2026-03-06T00:00:00.000+0000"),
                    _jira_issue("10001", "PLAT-2", "2026-03-06T00:00:00.000+0000"),
                ],
            }
            return httpx.Response(200, json=payload, request=httpx.Request(method, url))

    pool = _RecordingPool()
    monkeypatch.setattr(connectors, "get_http_client_pool", lambda: pool, raising=True)

    await connectors._execute_jira_project_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert run.status == "completed"
    assert pool.jqls
    assert 'updated >= "2026-03-06T00:00:00.000+0000"' in pool.jqls[0]
    assert seen.get("created_issue_keys") == ["PLAT-2"]
    assert int((run.stats or {}).get("skipped_boundary_duplicates") or 0) == 1
    assert (run.stats or {}).get("last_modified_ids") == ["10001"]


def test_soft_disable_jira_documents_missing_from_full_sync_marks_docs_disabled(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)
    base_url = "https://example.atlassian.net"
    project_key = "PLAT"

    class _Doc:
        def __init__(self, issue_key: str, *, disabled_at=None, project: str = project_key) -> None:  # noqa: ANN001
            self.id = uuid.uuid4()
            self.archived_at = None
            self.disabled_at = disabled_at
            self.doc_metadata = {
                "source_url": f"{base_url}/browse/{issue_key}",
                "connector": {
                    "connector_id": "jira_project",
                    "base_url": base_url,
                    "project_key": project,
                    "issue_key": issue_key,
                    "issue_url": f"{base_url}/browse/{issue_key}",
                },
            }

    active_missing = _Doc("PLAT-1")
    active_seen = _Doc("PLAT-2")
    already_disabled = _Doc("PLAT-3", disabled_at=now)
    other_project = _Doc("OTHER-1", project="OTHER")
    docs = [active_missing, active_seen, already_disabled, other_project]

    class _DocQuery:
        def __init__(self, docs_in):  # noqa: ANN001
            self._docs = list(docs_in or [])
            self._limit: int | None = None

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def distinct(self, *_a, **_k):  # noqa: ANN001
            return self

        def order_by(self, *_a, **_k):  # noqa: ANN001
            return self

        def limit(self, n: int):  # noqa: ANN001
            self._limit = int(n)
            return self

        def all(self):  # noqa: ANN201
            if self._limit is not None and self._limit > 0:
                return list(self._docs)[: self._limit]
            return list(self._docs)

    class _DocDB:
        def __init__(self, docs_in):  # noqa: ANN001
            self._docs = list(docs_in or [])

        def query(self, _model):  # noqa: ANN001
            return _DocQuery(self._docs)

    monkeypatch.setattr(connectors, "_now", lambda: now, raising=True)

    removed_issues_reconciled, removed_documents_disabled = connectors._soft_disable_jira_documents_missing_from_full_sync(
        _DocDB(docs),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        base_url=base_url,
        project_key=project_key,
        seen_issue_urls={f"{base_url}/browse/PLAT-2"},
    )

    assert removed_issues_reconciled == 1
    assert removed_documents_disabled == 1
    assert active_missing.disabled_at == now
    assert active_seen.disabled_at is None
    assert already_disabled.disabled_at == now
    assert other_project.disabled_at is None


def test_soft_disable_jira_attachment_documents_missing_from_issue_marks_only_missing_attachments_disabled(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)
    base_url = "https://example.atlassian.net"
    project_key = "PLAT"
    issue_url = f"{base_url}/browse/PLAT-1"

    class _Doc:
        def __init__(self, attachment_id: str, download_url: str, *, issue: str = issue_url) -> None:  # noqa: ANN001
            self.id = uuid.uuid4()
            self.archived_at = None
            self.disabled_at = None
            self.doc_metadata = {
                "connector": {
                    "connector_id": "jira_project",
                    "doc_kind": "attachment",
                    "base_url": base_url,
                    "project_key": project_key,
                    "issue_url": issue,
                    "attachment_id": attachment_id,
                    "download_url": download_url,
                }
            }

    active_missing = _Doc("2001", "https://example.atlassian.net/secure/attachment/2001/missing.pdf")
    active_seen = _Doc("2002", "https://example.atlassian.net/secure/attachment/2002/seen.pdf")
    other_issue = _Doc("2003", "https://example.atlassian.net/secure/attachment/2003/other.pdf", issue=f"{base_url}/browse/PLAT-2")
    docs = [active_missing, active_seen, other_issue]

    class _DocQuery:
        def __init__(self, docs_in):  # noqa: ANN001
            self._docs = list(docs_in or [])

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def order_by(self, *_a, **_k):  # noqa: ANN001
            return self

        def limit(self, _n: int):  # noqa: ANN001
            return self

        def all(self):  # noqa: ANN201
            return list(self._docs)

    class _DocDB:
        def __init__(self, docs_in):  # noqa: ANN001
            self._docs = list(docs_in or [])

        def query(self, _model):  # noqa: ANN001
            return _DocQuery(self._docs)

    monkeypatch.setattr(connectors, "_now", lambda: now, raising=True)

    disabled = connectors._soft_disable_jira_attachment_documents_missing_from_issue(
        _DocDB(docs),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        base_url=base_url,
        project_key=project_key,
        issue_url=issue_url,
        seen_attachment_urls={"https://example.atlassian.net/secure/attachment/2002/seen.pdf"},
    )

    assert disabled == 1
    assert active_missing.disabled_at == now
    assert active_seen.disabled_at is None
    assert other_issue.disabled_at is None
