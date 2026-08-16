import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1 import observability as obs_mod
from app.core.database import get_db


class _DummyDB:
    def query(self, _model):  # noqa: ANN001
        return self

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):  # noqa: ANN201
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _make_client(*, tenant_id: uuid.UUID, account_id: str = "acct-1") -> TestClient:
    app = FastAPI()
    app.include_router(obs_mod.router, prefix="/api/v1/observability")
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: account_id
    return TestClient(app)


def test_index_audit_reconcile_request_writes_pii_safe_audit_event(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    captured: dict[str, object] = {}

    class _AuditDB:
        def commit(self) -> None:
            captured["committed"] = True

        def rollback(self) -> None:
            captured["rolled_back"] = True

    def _audit(_db, **kwargs):  # noqa: ANN001, ANN202
        captured.update(kwargs)

    monkeypatch.setattr("app.services.audit_log_service.audit_log_event", _audit, raising=True)

    obs_mod._audit_index_reconcile_request(
        _AuditDB(),  # type: ignore[arg-type]
        tenant_id=tenant_id,
        account_id="acct-1",
        dataset_id=dataset_id,
        document_id=document_id,
        scope="document",
        status="enqueued",
        dry_run=False,
        limit=25,
        job_id="job-1",
    )

    assert captured["action"] == "index_audit.reconcile.request"
    assert captured["resource_type"] == "document"
    assert captured["resource_id"] == str(document_id)
    assert captured["details"] == {
        "dataset_id": str(dataset_id),
        "document_id": str(document_id),
        "scope": "document",
        "status": "enqueued",
        "job_id": "job-1",
        "dry_run": False,
        "limit": 25,
    }
    assert captured["committed"] is True
    assert "rolled_back" not in captured


def test_index_audit_requires_authenticated_account() -> None:
    app = FastAPI()
    app.include_router(obs_mod.router, prefix="/api/v1/observability")

    response = TestClient(app).get(f"/api/v1/observability/index-audit?dataset_id={uuid.uuid4()}")

    assert response.status_code == 401

    post_response = TestClient(app).post(
        "/api/v1/observability/index-audit/reconcile-jobs",
        json={"dataset_id": str(uuid.uuid4())},
    )
    assert post_response.status_code == 401


def test_index_audit_exposes_channel_summary(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    import app.services.index_audit_service as audit_service

    monkeypatch.setattr(
        audit_service,
        "run_dataset_index_audit",
        lambda **_kwargs: {
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "vector_backend": "milvus",
            "active_documents": 2,
            "active_chunks": 10,
            "vector_id_missing": 1,
            "vector_ids_checked": 3,
            "vector_ids_missing_in_backend": 1,
            "vector_ids_missing_in_backend_sample": ["missing-1"],
            "milvus_ids_sampled": 2,
            "milvus_orphan_ids_sample": ["orphan-1"],
            "index_channels": {
                "required_pending_documents": 1,
                "required_error_documents": 1,
                "optional_disabled_documents": 2,
                "optional_skipped_documents": 0,
            },
        },
        raising=True,
    )

    response = _make_client(tenant_id=tenant_id).get(
        f"/api/v1/observability/index-audit?dataset_id={dataset_id}"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dataset_id"] == str(dataset_id)
    assert body["index_channels"]["required_pending_documents"] == 1
    assert body["index_channels"]["optional_disabled_documents"] == 2


def test_index_audit_reconcile_returns_noop_when_document_is_ready(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    import app.services.index_audit_service as audit_service

    monkeypatch.setattr(
        audit_service,
        "get_index_audit_reconcile_document_state",
        lambda **_kwargs: {
            "document": SimpleNamespace(id=document_id),
            "current_index_readiness": {"ready": True, "pending_channels": [], "error_channels": []},
            "already_ready": True,
        },
        raising=True,
    )

    response = _make_client(tenant_id=tenant_id).post(
        "/api/v1/observability/index-audit/reconcile",
        json={"dataset_id": str(dataset_id), "document_id": str(document_id)},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "noop_ready"
    assert body["reason"] == "document_index_channels_already_ready"
    assert body["task_id"] is None


def test_index_audit_reconcile_enqueues_document_job(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    import app.services.index_audit_service as audit_service

    monkeypatch.setattr(
        audit_service,
        "get_index_audit_reconcile_document_state",
        lambda **_kwargs: {
            "document": SimpleNamespace(id=document_id),
            "current_index_readiness": {"ready": False, "pending_channels": ["bm25"], "error_channels": []},
            "already_ready": False,
        },
        raising=True,
    )

    async def _enqueue(**_kwargs):  # noqa: ANN202
        return {
            "schema": "mimirq.index_audit_reconcile.v1",
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "document_id": str(document_id),
            "scope": "document",
            "status": "enqueued",
            "reason": None,
            "task_id": "rebuild-task-1",
        }

    monkeypatch.setattr(audit_service, "enqueue_index_audit_reconcile", _enqueue, raising=True)

    response = _make_client(tenant_id=tenant_id).post(
        "/api/v1/observability/index-audit/reconcile",
        json={"dataset_id": str(dataset_id), "document_id": str(document_id)},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "enqueued"
    assert body["task_id"] == "rebuild-task-1"
    assert body["current_index_readiness"]["pending_channels"] == ["bm25"]


def test_index_audit_reconcile_rejects_missing_document_in_dataset(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    import app.services.index_audit_service as audit_service

    monkeypatch.setattr(
        audit_service,
        "get_index_audit_reconcile_document_state",
        lambda **_kwargs: None,
        raising=True,
    )

    response = _make_client(tenant_id=tenant_id).post(
        "/api/v1/observability/index-audit/reconcile",
        json={"dataset_id": str(dataset_id), "document_id": str(document_id)},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "document not found in dataset"


def test_index_audit_reconcile_status_returns_legacy_unknown(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    import app.services.index_audit_service as audit_service

    monkeypatch.setattr(
        audit_service,
        "get_index_audit_reconcile_document_status",
        lambda **_kwargs: {
            "schema": "mimirq.index_audit_reconcile_status.v1",
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "document_id": str(document_id),
            "status": "legacy_unknown",
            "reason": "document_has_no_current_pipeline_channel_rows",
            "legacy": True,
            "ready": True,
            "channel_rows_present": 0,
            "current_index_readiness": {"ready": True, "statuses": {"kg": {"legacy": True}}},
        },
        raising=True,
    )

    response = _make_client(tenant_id=tenant_id).get(
        f"/api/v1/observability/index-audit/reconcile-status?dataset_id={dataset_id}&document_id={document_id}"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "legacy_unknown"
    assert body["legacy"] is True
    assert body["channel_rows_present"] == 0
    assert body["current_index_readiness"]["ready"] is True


def test_index_audit_reconcile_status_returns_pending_and_404(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    missing_document_id = uuid.uuid4()
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    import app.services.index_audit_service as audit_service

    def _status(**kwargs):  # noqa: ANN202
        if kwargs["document_id"] == missing_document_id:
            return None
        return {
            "schema": "mimirq.index_audit_reconcile_status.v1",
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "document_id": str(document_id),
            "status": "pending",
            "reason": "document_index_channels_pending",
            "legacy": False,
            "ready": False,
            "channel_rows_present": 2,
            "current_index_readiness": {"ready": False, "pending_channels": ["bm25"], "error_channels": []},
        }

    monkeypatch.setattr(audit_service, "get_index_audit_reconcile_document_status", _status, raising=True)

    client = _make_client(tenant_id=tenant_id)
    response = client.get(
        f"/api/v1/observability/index-audit/reconcile-status?dataset_id={dataset_id}&document_id={document_id}"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["legacy"] is False
    assert body["ready"] is False
    assert body["current_index_readiness"]["pending_channels"] == ["bm25"]

    missing = client.get(
        f"/api/v1/observability/index-audit/reconcile-status?dataset_id={dataset_id}&document_id={missing_document_id}"
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "document not found in dataset"


def test_index_audit_reconcile_job_enqueue_defaults_to_dataset_dry_run(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(obs_mod.DatasetService, "get_dataset", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(obs_mod.settings, "TASK_QUEUE_ENABLED", True, raising=False)

    captured: dict[str, object] = {}

    async def _enqueue(**kwargs):  # noqa: ANN202
        captured.update(kwargs)
        return "index-audit-job-1"

    monkeypatch.setattr("app.tasks.queue.enqueue_index_audit_reconcile_job", _enqueue, raising=True)

    response = _make_client(tenant_id=tenant_id).post(
        "/api/v1/observability/index-audit/reconcile-jobs",
        json={"dataset_id": str(dataset_id)},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_name"] == "reconcile_index_audit_job"
    assert body["scope"] == "dataset"
    assert body["dry_run"] is True
    assert body["limit"] == 100
    assert body["status"] == "enqueued"
    assert body["legacy_unknown_report_only"] is True
    assert captured == {
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "document_id": None,
        "requested_by": "acct-1",
        "limit": 100,
        "dry_run": True,
        "job_id": f"index-audit-reconcile-job:{tenant_id}:{dataset_id}:dataset:100:1",
    }


def test_index_audit_reconcile_job_enqueue_validates_document_scope_and_duplicate(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    missing_document_id = uuid.uuid4()
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(obs_mod.DatasetService, "get_dataset", lambda *_args, **_kwargs: object(), raising=True)

    import app.services.index_audit_service as audit_service

    monkeypatch.setattr(
        audit_service,
        "get_index_audit_reconcile_document_state",
        lambda **kwargs: (
            None
            if kwargs["document_id"] == missing_document_id
            else {"document": SimpleNamespace(id=document_id), "current_index_readiness": {}, "already_ready": False}
        ),
        raising=True,
    )

    async def _enqueue(**_kwargs):  # noqa: ANN202
        return None

    monkeypatch.setattr("app.tasks.queue.enqueue_index_audit_reconcile_job", _enqueue, raising=True)
    monkeypatch.setattr(obs_mod.settings, "TASK_QUEUE_ENABLED", True, raising=False)

    client = _make_client(tenant_id=tenant_id)
    missing = client.post(
        "/api/v1/observability/index-audit/reconcile-jobs",
        json={"dataset_id": str(dataset_id), "document_id": str(missing_document_id), "limit": 25, "dry_run": False},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "document not found in dataset"

    response = client.post(
        "/api/v1/observability/index-audit/reconcile-jobs",
        json={"dataset_id": str(dataset_id), "document_id": str(document_id), "limit": 25, "dry_run": False},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "document"
    assert body["dry_run"] is False
    assert body["limit"] == 25
    assert body["status"] == "already_queued"
    assert body["reason"] == "duplicate_job"
    assert body["job_id"] == f"index-audit-reconcile-job:{tenant_id}:{dataset_id}:{document_id}:25:0"


def test_index_audit_reconcile_job_enqueue_reports_queue_disabled(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(obs_mod.DatasetService, "get_dataset", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(obs_mod.settings, "TASK_QUEUE_ENABLED", False, raising=False)

    async def _enqueue(**_kwargs):  # noqa: ANN202
        return None

    monkeypatch.setattr("app.tasks.queue.enqueue_index_audit_reconcile_job", _enqueue, raising=True)

    response = _make_client(tenant_id=tenant_id).post(
        "/api/v1/observability/index-audit/reconcile-jobs",
        json={"dataset_id": str(dataset_id)},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "not_enqueued"
    assert body["reason"] == "task_queue_disabled"
