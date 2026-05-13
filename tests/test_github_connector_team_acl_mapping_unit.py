from __future__ import annotations

import uuid

import pytest

from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_github_repo_connector_applies_team_acl_via_external_id(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors
    import app.api.v1.connectors_github_repo as connectors_github_repo
    from app.models.connector import ConnectorRun
    from app.rag.core.hashing import stable_hash

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()
    requested_by = "test-account"

    connectors_github_repo._leader_module = connectors

    # Fake run in DB.
    run = type(
        "_Run",
        (),
        {
            "id": run_id,
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "connector_id": "github_repo",
            "requested_by": requested_by,
            "status": "pending",
            "config": {
                "repo": "acme/demo",
                "branch": "main",
                "max_files": 1,
                "include_extensions": [".md"],
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

    # Fake GitHub tree API call (files listing).
    class _FakeResp:
        def __init__(self, status_code: int, payload):  # noqa: ANN001
            self.status_code = status_code
            self._payload = payload

        def json(self):  # noqa: ANN201
            return self._payload

    class _FakeClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN001
            return None

        async def __aenter__(self):  # noqa: ANN201
            await yield_control()
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN201
            await yield_control()
            return False

        async def get(self, url: str, headers=None):  # noqa: ANN001, ANN201
            await yield_control()
            assert "/git/trees/" in url
            return _FakeResp(
                200,
                {
                    "tree": [
                        {"type": "blob", "path": "README.md"},
                    ]
                },
            )

    monkeypatch.setattr(connectors.httpx, "AsyncClient", lambda *_a, **_k: _FakeClient(), raising=True)

    # Stub: ingest always returns a new doc object.
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

    # Capture applied group ACLs.
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

    def _delta_stub(_db, *, source_url: str, **_k):  # noqa: ANN001
        seen["delta_source_url"] = source_url
        return 2

    monkeypatch.setattr(connectors, "_delta_sync_connector_documents_acl_by_source_url", _delta_stub, raising=True)

    # Source ACL mapping stubs (this is what we are adding in Wave26-T22).
    expected_external_ids = ["github:team:acme/dev"]
    mapped_group_id = uuid.uuid4()

    async def _fake_fetch_team_keys(*_a, **_k):  # noqa: ANN001, ANN201
        await yield_control()
        return list(expected_external_ids)

    monkeypatch.setattr(connectors, "_github_fetch_repo_team_principal_keys", _fake_fetch_team_keys, raising=True)

    def _fake_resolve_groups(*_a, **_k):  # noqa: ANN001
        seen["external_ids"] = list(_k.get("external_ids") or [])
        return {mapped_group_id}

    monkeypatch.setattr(connectors, "_resolve_tenant_group_ids_by_external_id", _fake_resolve_groups, raising=True)

    await connectors._execute_github_repo_run(run_id=run_id, tenant_id=tenant_id, requested_by=requested_by)

    assert run.status == "completed"
    assert set(seen.get("external_ids") or []) == set(expected_external_ids)
    assert set(seen.get("group_ids") or []) == {str(mapped_group_id)}
    assert "github_repo.source_acl.applied" in (seen.get("audit_actions") or [])
    assert (seen.get("audit_details_by_action") or {}).get("github_repo.source_acl.applied", {}).get("mapped_group_count") == 1
    assert "github_repo.source_acl.delta_sync" in (seen.get("audit_actions") or [])
    assert (seen.get("audit_details_by_action") or {}).get("github_repo.source_acl.delta_sync", {}).get("updated_documents") == 2
    assert (seen.get("audit_details_by_action") or {}).get("github_repo.source_acl.delta_sync", {}).get("updated_sources") == 1
    assert "raw.githubusercontent.com" in str(seen.get("delta_source_url") or "")
    assert (run.stats or {}).get("acl_delta_sync_updated_documents") == 2
    assert (run.stats or {}).get("acl_delta_sync_updated_sources") == 1

    assert len(created_docs) == 1
    prov = (created_docs[0].doc_metadata or {}).get("acl_provenance")
    assert isinstance(prov, dict)
    assert prov.get("schema") == "mimirq.document_acl_provenance.v1"
    assert (prov.get("applied_by") or {}).get("connector_id") == "github_repo"
    assert (prov.get("applied_by") or {}).get("run_id") == str(run_id)
    assert (prov.get("effective_access") or {}).get("mode") == "partial_members"

    src = prov.get("source_acl") or {}
    assert src.get("mode") == "inherit"
    assert src.get("fallback_used") is False
    assert src.get("principal_hash_alg") == "sha256"
    assert stable_hash(expected_external_ids[0], length=32) in (src.get("principal_hashes") or [])
    assert expected_external_ids[0] not in str(prov)
