from __future__ import annotations

import uuid

import httpx
import pytest


@pytest.mark.asyncio
async def test_jira_connector_ingests_issue_and_applies_source_acl(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors
    from app.models.connector import ConnectorRun
    from app.rag.core.hashing import stable_hash

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()
    requested_by = "test-account"

    run = type(
        "_Run",
        (),
        {
            "id": run_id,
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "connector_id": "jira_project",
            "requested_by": requested_by,
            "status": "pending",
            "config": {
                "base_url": "https://example.atlassian.net",
                "project_key": "PLAT",
                "max_issues": 1,
                "page_size": 1,
                "chunk_strategy": "jira_ticket",
                "include_comments": True,
                "max_comments_per_issue": 5,
                "source_acl": {"mode": "inherit"},
            },
            "stats": {},
            "error_message": None,
            "task_id": None,
            "started_at": None,
            "finished_at": None,
            "documents": [],
        },
    )()

    class _DummyQuery:
        def __init__(self, model):  # noqa: ANN001
            self.model = model

        def options(self, *_a, **_k):  # noqa: ANN001
            return self

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN201
            if self.model is ConnectorRun:
                return run
            return None

    class _DummyDB:
        def query(self, model):  # noqa: ANN001
            return _DummyQuery(model)

        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

        def close(self) -> None:
            return None

    dummy_db = _DummyDB()
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)

    issue = {
        "id": "10000",
        "key": "PLAT-42",
        "fields": {
            "summary": "Sync ACL drift to search index",
            "description": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Description body"}]}],
            },
            "updated": "2026-03-02T12:34:56.000+0000",
            "issuetype": {"name": "Bug"},
            "priority": {"name": "High"},
            "status": {"name": "In Progress"},
            "security": {"id": "10001", "name": "Executives"},
            "comment": {
                "comments": [
                    {
                        "author": {"displayName": "Ada"},
                        "created": "2026-03-02T13:00:00.000+0000",
                        "visibility": {"type": "role", "value": "Developers"},
                        "body": {
                            "type": "doc",
                            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Comment body"}]}],
                        },
                    }
                ]
            },
        },
        "renderedFields": {
            "description": "<p>Description body</p>",
            "comment": {"comments": [{"body": "<p>Comment body</p>"}]},
        },
    }

    class _FakePool:
        async def request_with_retry(self, method: str, url: str, **kwargs):  # noqa: ANN201
            params = kwargs.get("params") or {}
            start_at = int(params.get("startAt", 0) or 0)
            if url.endswith("/rest/api/3/search") and start_at == 0:
                payload = {"startAt": 0, "maxResults": 1, "total": 1, "issues": [issue]}
                return httpx.Response(200, json=payload, request=httpx.Request(method, url))
            if url.endswith("/rest/api/3/search"):
                payload = {"startAt": start_at, "maxResults": 1, "total": 1, "issues": []}
                return httpx.Response(200, json=payload, request=httpx.Request(method, url))
            raise AssertionError(f"unexpected jira url: {url}")

    monkeypatch.setattr(connectors, "get_http_client_pool", lambda: _FakePool(), raising=True)

    created_doc_id = uuid.uuid4()

    class _Doc:
        def __init__(self) -> None:
            self.id = created_doc_id
            self.access_mode = None
            self.owner_id = None
            self.doc_metadata = {}

    created_docs: list[_Doc] = []
    seen: dict[str, object] = {}

    async def _fake_ingest(*_a, **_k):  # noqa: ANN001, ANN201
        body = _k.get("body")
        seen["ingest_filename"] = getattr(body, "filename", None)
        seen["ingest_source_url"] = getattr(body, "source_url", None)
        seen["ingest_chunk_strategy"] = getattr(body, "chunk_strategy", None)
        seen["ingest_html"] = getattr(body, "html", "")
        d = _Doc()
        created_docs.append(d)
        return d

    monkeypatch.setattr(connectors, "_ingest_local_html_request", _fake_ingest, raising=True)

    import app.services.audit_log_service as audit_log_service

    def _audit_stub(_db, *, action: str, **kwargs):  # noqa: ANN001
        seen.setdefault("audit_actions", []).append(action)
        details = dict(kwargs.get("details") or {})
        by_action = seen.setdefault("audit_details_by_action", {})
        if isinstance(by_action, dict):
            by_action[action] = details

    monkeypatch.setattr(audit_log_service, "audit_log_event", _audit_stub, raising=True)

    monkeypatch.setattr(connectors.DocumentPermissionService, "update_partial_member_list", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors.DocumentPermissionService, "clear_partial_member_list", lambda *_a, **_k: None, raising=True)

    def _upd_groups(_db, _tenant_id, _doc_id, group_ids, **_k):  # noqa: ANN001
        seen["group_ids"] = list(group_ids)

    monkeypatch.setattr(connectors.DocumentGroupPermissionService, "update_partial_group_list", _upd_groups, raising=True)
    monkeypatch.setattr(connectors.DocumentGroupPermissionService, "clear_partial_group_list", lambda *_a, **_k: None, raising=True)

    mapped_group_id = uuid.uuid4()

    def _fake_resolve_groups(*_a, **_k):  # noqa: ANN001
        seen["external_ids"] = list(_k.get("external_ids") or [])
        return {mapped_group_id}

    monkeypatch.setattr(connectors, "_resolve_tenant_group_ids_by_external_id", _fake_resolve_groups, raising=True)

    def _delta_stub(*_a, **_k):  # noqa: ANN001
        seen["delta_issue_url"] = _k.get("issue_url")
        return 2

    monkeypatch.setattr(connectors, "_delta_sync_jira_documents_acl_by_issue_url", _delta_stub, raising=False)

    await connectors._execute_jira_project_run(run_id=run_id, tenant_id=tenant_id, requested_by=requested_by)

    assert run.status == "completed"
    assert seen.get("ingest_filename") == "PLAT-42.html"
    assert seen.get("ingest_source_url") == "https://example.atlassian.net/browse/PLAT-42"
    assert seen.get("ingest_chunk_strategy") == "jira_ticket"
    assert "Summary" in str(seen.get("ingest_html") or "")
    assert "Comments" in str(seen.get("ingest_html") or "")
    assert set(seen.get("external_ids") or []) == {
        "jira:policy:security-level/10001",
        "jira:role:developers",
    }
    assert set(seen.get("group_ids") or []) == {str(mapped_group_id)}
    assert seen.get("delta_issue_url") == "https://example.atlassian.net/browse/PLAT-42"
    assert (run.stats or {}).get("acl_delta_sync_updated_documents") == 2
    assert (run.stats or {}).get("acl_delta_sync_updated_sources") == 1
    assert (run.stats or {}).get("last_modified") == "2026-03-02T12:34:56.000+0000"
    assert "jira_project.source_acl.delta_sync" in (seen.get("audit_actions") or [])
    assert (seen.get("audit_details_by_action") or {}).get("jira_project.source_acl.delta_sync", {}).get("updated_documents") == 2

    assert len(created_docs) == 1
    prov = (created_docs[0].doc_metadata or {}).get("acl_provenance")
    assert isinstance(prov, dict)
    assert prov.get("schema") == "mimirq.document_acl_provenance.v1"
    assert (prov.get("applied_by") or {}).get("connector_id") == "jira_project"
    assert (prov.get("applied_by") or {}).get("run_id") == str(run_id)

    src = prov.get("source_acl") or {}
    assert src.get("mode") == "inherit"
    assert src.get("restricted") is True
    assert src.get("fallback_used") is False
    assert stable_hash("jira:policy:security-level/10001", length=32) in (src.get("principal_hashes") or [])
    assert stable_hash("jira:role:developers", length=32) in (src.get("principal_hashes") or [])
    assert "jira:policy:security-level/10001" not in str(prov)

    meta = created_docs[0].doc_metadata or {}
    assert meta.get("source_last_modified_source") == "connector:jira:updated"
    assert meta.get("source_last_modified_raw") == "2026-03-02T12:34:56.000+0000"
    assert (meta.get("connector") or {}).get("connector_id") == "jira_project"
    assert (meta.get("connector") or {}).get("project_key") == "PLAT"
    assert (meta.get("connector") or {}).get("issue_key") == "PLAT-42"


@pytest.mark.asyncio
async def test_jira_connector_ingests_attachments_with_issue_acl(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors
    from app.models.connector import ConnectorRun

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()
    requested_by = "test-account"

    run = type(
        "_Run",
        (),
        {
            "id": run_id,
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "connector_id": "jira_project",
            "requested_by": requested_by,
            "status": "pending",
            "config": {
                "base_url": "https://example.atlassian.net",
                "project_key": "PLAT",
                "max_issues": 1,
                "page_size": 1,
                "chunk_strategy": "jira_ticket",
                "include_comments": False,
                "include_attachments": True,
                "max_attachments_per_issue": 2,
                "max_total_attachments": 5,
                "source_acl": {"mode": "inherit"},
            },
            "stats": {},
            "error_message": None,
            "task_id": None,
            "started_at": None,
            "finished_at": None,
            "documents": [],
        },
    )()

    class _DummyQuery:
        def __init__(self, model):  # noqa: ANN001
            self.model = model

        def options(self, *_a, **_k):  # noqa: ANN001
            return self

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN201
            if self.model is ConnectorRun:
                return run
            return None

    class _DummyDB:
        def query(self, model):  # noqa: ANN001
            return _DummyQuery(model)

        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(connectors, "SessionLocal", lambda: _DummyDB(), raising=True)

    issue = {
        "id": "10000",
        "key": "PLAT-42",
        "fields": {
            "summary": "Sync ACL drift to search index",
            "description": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Description body"}]}],
            },
            "updated": "2026-03-02T12:34:56.000+0000",
            "issuetype": {"name": "Bug"},
            "priority": {"name": "High"},
            "status": {"name": "In Progress"},
            "security": {"id": "10001", "name": "Executives"},
            "comment": {"comments": []},
            "attachment": [
                {
                    "id": "2001",
                    "filename": "design.pdf",
                    "content": "https://example.atlassian.net/secure/attachment/2001/design.pdf",
                }
            ],
        },
        "renderedFields": {
            "description": "<p>Description body</p>",
            "comment": {"comments": []},
        },
    }

    class _FakePool:
        async def request_with_retry(self, method: str, url: str, **kwargs):  # noqa: ANN201
            params = kwargs.get("params") or {}
            start_at = int(params.get("startAt", 0) or 0)
            if url.endswith("/rest/api/3/search") and start_at == 0:
                payload = {"startAt": 0, "maxResults": 1, "total": 1, "issues": [issue]}
                return httpx.Response(200, json=payload, request=httpx.Request(method, url))
            if url.endswith("/rest/api/3/search"):
                payload = {"startAt": start_at, "maxResults": 1, "total": 1, "issues": []}
                return httpx.Response(200, json=payload, request=httpx.Request(method, url))
            raise AssertionError(f"unexpected jira url: {url}")

    monkeypatch.setattr(connectors, "get_http_client_pool", lambda: _FakePool(), raising=True)

    issue_doc_id = uuid.uuid4()
    attachment_doc_id = uuid.uuid4()

    class _Doc:
        def __init__(self, doc_id: uuid.UUID) -> None:
            self.id = doc_id
            self.access_mode = None
            self.owner_id = None
            self.doc_metadata = {}

    issue_doc = _Doc(issue_doc_id)
    attachment_doc = _Doc(attachment_doc_id)
    seen: dict[str, object] = {}

    async def _fake_ingest_issue(*_a, **_k):  # noqa: ANN001, ANN201
        seen["issue_html_source_url"] = getattr(_k.get("body"), "source_url", None)
        return issue_doc

    async def _fake_ingest_attachment(*_a, **_k):  # noqa: ANN001, ANN201
        body = _k.get("body")
        seen["attachment_url"] = getattr(body, "url", None)
        seen["attachment_filename"] = getattr(body, "filename", None)
        seen["attachment_fetch_headers"] = getattr(body, "fetch_headers", None)
        return attachment_doc

    monkeypatch.setattr(connectors, "_ingest_local_html_request", _fake_ingest_issue, raising=True)
    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_attachment, raising=True)

    monkeypatch.setattr(connectors.DocumentPermissionService, "update_partial_member_list", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors.DocumentPermissionService, "clear_partial_member_list", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors.DocumentGroupPermissionService, "clear_partial_group_list", lambda *_a, **_k: None, raising=True)

    mapped_group_id = uuid.uuid4()

    def _upd_groups(_db, _tenant_id, doc_id, group_ids, **_k):  # noqa: ANN001
        seen.setdefault("group_updates", []).append((doc_id, list(group_ids)))

    monkeypatch.setattr(connectors.DocumentGroupPermissionService, "update_partial_group_list", _upd_groups, raising=True)
    monkeypatch.setattr(
        connectors,
        "_resolve_tenant_group_ids_by_external_id",
        lambda *_a, **_k: {mapped_group_id},
        raising=True,
    )

    def _delta_issue_acl_stub(*_a, **_k):  # noqa: ANN001
        seen["delta_issue_url"] = _k.get("issue_url")
        return 2

    def _disable_missing_attachments_stub(*_a, **_k):  # noqa: ANN001
        seen["attachment_reconcile_issue_url"] = _k.get("issue_url")
        seen["seen_attachment_urls"] = sorted(_k.get("seen_attachment_urls") or [])
        return 1

    monkeypatch.setattr(connectors, "_delta_sync_jira_documents_acl_by_issue_url", _delta_issue_acl_stub, raising=False)
    monkeypatch.setattr(connectors, "_soft_disable_jira_attachment_documents_missing_from_issue", _disable_missing_attachments_stub, raising=False)

    await connectors._execute_jira_project_run(run_id=run_id, tenant_id=tenant_id, requested_by=requested_by)

    assert run.status == "completed"
    assert seen.get("issue_html_source_url") == "https://example.atlassian.net/browse/PLAT-42"
    assert seen.get("attachment_url") == "https://example.atlassian.net/secure/attachment/2001/design.pdf"
    assert seen.get("attachment_filename") == "design.pdf"
    assert seen.get("delta_issue_url") == "https://example.atlassian.net/browse/PLAT-42"
    assert seen.get("attachment_reconcile_issue_url") == "https://example.atlassian.net/browse/PLAT-42"
    assert seen.get("seen_attachment_urls") == ["https://example.atlassian.net/secure/attachment/2001/design.pdf"]
    assert (attachment_doc.doc_metadata.get("connector") or {}).get("doc_kind") == "attachment"
    assert (attachment_doc.doc_metadata.get("connector") or {}).get("issue_key") == "PLAT-42"
    assert (attachment_doc.doc_metadata.get("connector") or {}).get("attachment_id") == "2001"
    assert len(seen.get("group_updates") or []) == 2
    assert (run.stats or {}).get("created_attachments") == 1
    assert (run.stats or {}).get("processed_attachments") == 1


@pytest.mark.asyncio
async def test_jira_connector_ingests_linked_artifacts_without_leaking_auth(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors
    from app.models.connector import ConnectorRun

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()
    requested_by = "test-account"

    run = type(
        "_Run",
        (),
        {
            "id": run_id,
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "connector_id": "jira_project",
            "requested_by": requested_by,
            "status": "pending",
            "config": {
                "base_url": "https://example.atlassian.net",
                "project_key": "PLAT",
                "max_issues": 1,
                "page_size": 1,
                "chunk_strategy": "jira_ticket",
                "include_comments": False,
                "include_linked_artifacts": True,
                "max_linked_artifacts_per_issue": 10,
                "max_total_linked_artifacts": 20,
                "auth": {"type": "basic", "username": "bot@example.com", "password": "token"},
                "source_acl": {"mode": "inherit"},
            },
            "stats": {},
            "error_message": None,
            "task_id": None,
            "started_at": None,
            "finished_at": None,
            "documents": [],
        },
    )()

    class _DummyQuery:
        def __init__(self, model):  # noqa: ANN001
            self.model = model

        def options(self, *_a, **_k):  # noqa: ANN001
            return self

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN201
            if self.model is ConnectorRun:
                return run
            return None

    class _DummyDB:
        def query(self, model):  # noqa: ANN001
            return _DummyQuery(model)

        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(connectors, "SessionLocal", lambda: _DummyDB(), raising=True)

    issue = {
        "id": "10000",
        "key": "PLAT-42",
        "fields": {
            "summary": "Linked artifacts",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "See "},
                            {
                                "type": "text",
                                "text": "spec",
                                "marks": [
                                    {
                                        "type": "link",
                                        "attrs": {"href": "https://example.atlassian.net/wiki/spaces/PLAT/pages/1/Spec"},
                                    }
                                ],
                            },
                            {"type": "text", "text": " and "},
                            {
                                "type": "text",
                                "text": "github",
                                "marks": [{"type": "link", "attrs": {"href": "https://github.com/org/repo/pull/1"}}],
                            },
                        ],
                    }
                ],
            },
            "updated": "2026-03-02T12:34:56.000+0000",
            "issuetype": {"name": "Task"},
            "priority": {"name": "High"},
            "status": {"name": "In Progress"},
            "security": {"id": "10001", "name": "Executives"},
            "comment": {"comments": []},
            "attachment": [],
        },
        "renderedFields": {
            "description": "<p>See spec and github</p>",
            "comment": {"comments": []},
        },
    }

    class _FakePool:
        async def request_with_retry(self, method: str, url: str, **kwargs):  # noqa: ANN201
            params = kwargs.get("params") or {}
            start_at = int(params.get("startAt", 0) or 0)
            if url.endswith("/rest/api/3/search") and start_at == 0:
                payload = {"startAt": 0, "maxResults": 1, "total": 1, "issues": [issue]}
                return httpx.Response(200, json=payload, request=httpx.Request(method, url))
            if url.endswith("/rest/api/3/search"):
                payload = {"startAt": start_at, "maxResults": 1, "total": 1, "issues": []}
                return httpx.Response(200, json=payload, request=httpx.Request(method, url))
            raise AssertionError(f"unexpected jira url: {url}")

    monkeypatch.setattr(connectors, "get_http_client_pool", lambda: _FakePool(), raising=True)

    issue_doc_id = uuid.uuid4()
    link_doc_ids = [uuid.uuid4(), uuid.uuid4()]

    class _Doc:
        def __init__(self, doc_id: uuid.UUID) -> None:
            self.id = doc_id
            self.access_mode = None
            self.owner_id = None
            self.doc_metadata = {}

    issue_doc = _Doc(issue_doc_id)
    link_docs = [_Doc(link_doc_ids[0]), _Doc(link_doc_ids[1])]
    seen: dict[str, object] = {}

    async def _fake_ingest_issue(*_a, **_k):  # noqa: ANN001, ANN201
        return issue_doc

    async def _fake_ingest_link(*_a, **_k):  # noqa: ANN001, ANN201
        body = _k.get("body")
        seen.setdefault("linked_urls", []).append(getattr(body, "url", None))
        seen.setdefault("linked_fetch_headers", []).append(getattr(body, "fetch_headers", None))
        return link_docs[len(seen.get("linked_urls") or []) - 1]

    monkeypatch.setattr(connectors, "_ingest_local_html_request", _fake_ingest_issue, raising=True)
    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_link, raising=True)

    monkeypatch.setattr(connectors.DocumentPermissionService, "update_partial_member_list", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors.DocumentPermissionService, "clear_partial_member_list", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors.DocumentGroupPermissionService, "clear_partial_group_list", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors.DocumentGroupPermissionService, "update_partial_group_list", lambda *_a, **_k: None, raising=True)

    mapped_group_id = uuid.uuid4()

    monkeypatch.setattr(
        connectors,
        "_resolve_tenant_group_ids_by_external_id",
        lambda *_a, **_k: {mapped_group_id},
        raising=True,
    )

    monkeypatch.setattr(connectors, "_delta_sync_jira_documents_acl_by_issue_url", lambda *_a, **_k: 0, raising=False)

    def _disable_missing_links_stub(*_a, **_k):  # noqa: ANN001
        seen["linked_reconcile_issue_url"] = _k.get("issue_url")
        seen["seen_linked_urls"] = sorted(_k.get("seen_link_urls") or [])
        return 0

    monkeypatch.setattr(connectors, "_soft_disable_jira_linked_artifact_documents_missing_from_issue", _disable_missing_links_stub, raising=False)

    await connectors._execute_jira_project_run(run_id=run_id, tenant_id=tenant_id, requested_by=requested_by)

    assert run.status == "completed"
    assert sorted(seen.get("linked_urls") or []) == [
        "https://example.atlassian.net/wiki/spaces/PLAT/pages/1/Spec",
        "https://github.com/org/repo/pull/1",
    ]
    # Do not leak Jira auth headers to third-party domains.
    assert (seen.get("linked_fetch_headers") or [None, None])[0] is not None
    assert (seen.get("linked_fetch_headers") or [None, None])[1] is None
    assert seen.get("linked_reconcile_issue_url") == "https://example.atlassian.net/browse/PLAT-42"
    assert seen.get("seen_linked_urls") == [
        "https://example.atlassian.net/wiki/spaces/PLAT/pages/1/Spec",
        "https://github.com/org/repo/pull/1",
    ]

    assert (link_docs[0].doc_metadata.get("connector") or {}).get("doc_kind") == "linked_artifact"
    assert (link_docs[0].doc_metadata.get("connector") or {}).get("issue_key") == "PLAT-42"
    assert (run.stats or {}).get("created_linked_artifacts") == 2
    assert (run.stats or {}).get("processed_linked_artifacts") == 2
