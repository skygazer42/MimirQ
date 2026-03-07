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
        seen["delta_source_url"] = _k.get("source_url")
        return 2

    monkeypatch.setattr(connectors, "_delta_sync_connector_documents_acl_by_source_url", _delta_stub, raising=True)

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
    assert seen.get("delta_source_url") == "https://example.atlassian.net/browse/PLAT-42"
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
