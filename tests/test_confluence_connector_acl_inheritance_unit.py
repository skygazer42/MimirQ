from __future__ import annotations

import uuid

import httpx
import pytest

from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_confluence_connector_applies_restriction_groups_as_doc_acl(monkeypatch):  # noqa: ANN001
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
            "connector_id": "confluence_space",
            "requested_by": requested_by,
            "status": "pending",
            "config": {
                "base_url": "https://example.atlassian.net/wiki",
                "space_key": "DOCS",
                "max_pages": 1,
                "page_size": 1,
                "ingest_method": "webui",
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

    # Fake Confluence API calls via the http client pool.
    class _FakePool:
        async def request_with_retry(self, method: str, url: str, **kwargs):  # noqa: ANN201
            await yield_control()
            if url.endswith("/content/search"):
                payload = {
                    "_links": {"base": "https://example.atlassian.net/wiki"},
                    "results": [
                        {
                            "id": "123",
                            "title": "Hello",
                            "version": {"when": "2026-03-01T00:00:00.000Z"},
                            "_links": {"webui": "/spaces/DOCS/pages/123/Hello"},
                        }
                    ],
                }
                return httpx.Response(200, json=payload, request=httpx.Request(method, url))

            if "/restriction/byOperation/read" in url:
                payload = {
                    "results": [
                        {
                            "restrictions": {
                                "group": {"results": [{"name": "confluence-users"}]},
                                "user": {"results": []},
                            }
                        }
                    ]
                }
                return httpx.Response(200, json=payload, request=httpx.Request(method, url))

            raise AssertionError(f"unexpected confluence url: {url}")

    monkeypatch.setattr(connectors, "get_http_client_pool", lambda: _FakePool(), raising=True)

    # Stub: ingest returns a doc object.
    created_doc_id = uuid.uuid4()

    class _Doc:
        def __init__(self) -> None:
            self.id = created_doc_id
            self.access_mode = None
            self.owner_id = None
            self.doc_metadata = {}

    created_docs: list[_Doc] = []

    async def _fake_ingest(*_a, **_k):  # noqa: ANN001, ANN201
        await yield_control()
        d = _Doc()
        created_docs.append(d)
        return d

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest, raising=True)

    seen: dict[str, object] = {}

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

    def _delta_stub(_db, *, page_id: str, **_k):  # noqa: ANN001
        seen["delta_page_id"] = page_id
        return 3

    monkeypatch.setattr(connectors, "_delta_sync_confluence_documents_acl_by_page_id", _delta_stub, raising=True)

    await connectors._execute_confluence_space_run(run_id=run_id, tenant_id=tenant_id, requested_by=requested_by)

    assert run.status == "completed"
    assert set(seen.get("external_ids") or []) == {"confluence:group:confluence-users"}
    assert set(seen.get("group_ids") or []) == {str(mapped_group_id)}
    assert seen.get("delta_page_id") == "123"
    assert (run.stats or {}).get("acl_delta_sync_updated_documents") == 3
    assert (run.stats or {}).get("acl_delta_sync_updated_sources") == 1
    assert "confluence_space.source_acl.delta_sync" in (seen.get("audit_actions") or [])
    assert (seen.get("audit_details_by_action") or {}).get("confluence_space.source_acl.delta_sync", {}).get("updated_documents") == 3
    assert (seen.get("audit_details_by_action") or {}).get("confluence_space.source_acl.delta_sync", {}).get("updated_pages") == 1

    assert len(created_docs) == 1
    prov = (created_docs[0].doc_metadata or {}).get("acl_provenance")
    assert isinstance(prov, dict)
    assert prov.get("schema") == "mimirq.document_acl_provenance.v1"
    assert (prov.get("applied_by") or {}).get("connector_id") == "confluence_space"
    assert (prov.get("applied_by") or {}).get("run_id") == str(run_id)

    src = prov.get("source_acl") or {}
    assert src.get("mode") == "inherit"
    assert src.get("restricted") is True
    assert src.get("fallback_used") is False
    assert stable_hash("confluence:group:confluence-users", length=32) in (src.get("principal_hashes") or [])
    assert "confluence:group:confluence-users" not in str(prov)


@pytest.mark.asyncio
async def test_confluence_incremental_replays_boundary_timestamp_and_skips_seen_page_ids(monkeypatch):  # noqa: ANN001
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
            "connector_id": "confluence_space",
            "requested_by": requested_by,
            "status": "pending",
            "config": {
                "base_url": "https://example.atlassian.net/wiki",
                "space_key": "DOCS",
                "max_pages": 5,
                "page_size": 5,
                "ingest_method": "webui",
                "_state": {
                    "last_modified": "2026-03-01T00:00:00.000Z",
                    "last_modified_ids": ["123"],
                },
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
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors, "_sync_connector_config_from_run", lambda *_a, **_k: None, raising=True)

    seen: dict[str, object] = {"ingested_ids": []}

    class _FakePool:
        async def request_with_retry(self, method: str, url: str, **kwargs):  # noqa: ANN201
            await yield_control()
            if url.endswith("/content/search"):
                params = kwargs.get("params") or {}
                seen["cql"] = params.get("cql")
                start = int(params.get("start", 0) or 0)
                if start > 0:
                    payload = {
                        "_links": {"base": "https://example.atlassian.net/wiki"},
                        "results": [],
                    }
                    return httpx.Response(200, json=payload, request=httpx.Request(method, url))
                payload = {
                    "_links": {"base": "https://example.atlassian.net/wiki"},
                    "results": [
                        {
                            "id": "123",
                            "title": "Seen Before",
                            "version": {"when": "2026-03-01T00:00:00.000Z"},
                            "_links": {"webui": "/spaces/DOCS/pages/123/Seen-Before"},
                        },
                        {
                            "id": "124",
                            "title": "New At Boundary",
                            "version": {"when": "2026-03-01T00:00:00.000Z"},
                            "_links": {"webui": "/spaces/DOCS/pages/124/New-At-Boundary"},
                        },
                    ],
                }
                return httpx.Response(200, json=payload, request=httpx.Request(method, url))
            raise AssertionError(f"unexpected confluence url: {url}")

    monkeypatch.setattr(connectors, "get_http_client_pool", lambda: _FakePool(), raising=True)

    async def _fake_ingest(*_a, **kwargs):  # noqa: ANN001, ANN201
        await yield_control()
        body = kwargs.get("body")
        source_url = getattr(body, "url", None)
        if source_url and "/pages/124/" in source_url:
            seen.setdefault("ingested_ids", []).append("124")
        elif source_url and "/pages/123/" in source_url:
            seen.setdefault("ingested_ids", []).append("123")
        doc = type("_Doc", (), {"id": uuid.uuid4(), "access_mode": None, "owner_id": None, "doc_metadata": {}})()
        return doc

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest, raising=True)

    await connectors._execute_confluence_space_run(run_id=run_id, tenant_id=tenant_id, requested_by=requested_by)

    assert run.status == "completed"
    assert 'lastmodified >= "2026-03-01T00:00:00.000Z"' in str(seen.get("cql") or "")
    assert seen.get("ingested_ids") == ["124"]
    assert (run.stats or {}).get("skipped_boundary_duplicates") == 1
    assert (run.stats or {}).get("last_modified_ids") == ["124"]
