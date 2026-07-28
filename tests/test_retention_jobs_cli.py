import json
import uuid
from types import SimpleNamespace

import pytest

import scripts.run_retention_jobs as cli


@pytest.fixture
def runtime_deps(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    deps = SimpleNamespace(
        settings=SimpleNamespace(DEFAULT_TENANT_ID=str(uuid.UUID(int=0))),
        SessionLocal=None,
        Dataset=None,
        Tenant=SimpleNamespace(id=object()),
        run_audit_log_retention=None,
        run_knowledge_asset_retention=None,
        run_regression_run_retention=None,
        parse_retention_policy_from_metadata=None,
        run_dataset_retention_sweep=None,
        run_semantic_cache_retention=None,
    )
    monkeypatch.setattr(cli, "_load_runtime_dependencies", lambda: deps)
    return deps


def test_retention_jobs_cli_runs_semantic_cache_dry_run(
    capsys: pytest.CaptureFixture[str],
    runtime_deps: SimpleNamespace,
) -> None:
    tenant_id = uuid.uuid4()
    calls: list[dict[str, object]] = []
    runtime_deps.run_semantic_cache_retention = (
        lambda **kwargs: calls.append(kwargs) or {"job": "semantic-cache", "deleted": 0, "eligible": 3, "failed": False}
    )

    rc = cli.main(
        [
            "--semantic-cache",
            "--dry-run",
            "--tenant-id",
            str(tenant_id),
            "--max-delete",
            "7",
            "--max-scan",
            "11",
        ]
    )

    assert rc == 0
    assert calls == [{"tenant_id": tenant_id, "dry_run": True, "max_delete": 7, "max_scan": 11}]
    body = json.loads(capsys.readouterr().out)
    assert body["ok"] is True
    assert body["results"] == [{"job": "semantic-cache", "deleted": 0, "eligible": 3, "failed": False}]


def test_retention_jobs_cli_runs_semantic_cache_execute_for_default_tenant(
    capsys: pytest.CaptureFixture[str],
    runtime_deps: SimpleNamespace,
) -> None:
    default_tenant = uuid.uuid4()
    calls: list[dict[str, object]] = []
    runtime_deps.settings.DEFAULT_TENANT_ID = str(default_tenant)
    runtime_deps.run_semantic_cache_retention = (
        lambda **kwargs: calls.append(kwargs) or {"job": "semantic-cache", "deleted": 2, "eligible": 2, "failed": False}
    )

    rc = cli.main(["--semantic-cache", "--execute", "--max-delete", "9", "--max-scan", "15"])

    assert rc == 0
    assert calls == [{"tenant_id": default_tenant, "dry_run": False, "max_delete": 9, "max_scan": 15}]
    body = json.loads(capsys.readouterr().out)
    assert body["results"][0]["deleted"] == 2


def test_retention_jobs_cli_returns_nonzero_on_semantic_cache_failure(
    capsys: pytest.CaptureFixture[str],
    runtime_deps: SimpleNamespace,
) -> None:
    runtime_deps.run_semantic_cache_retention = lambda **_kwargs: {
        "job": "semantic-cache",
        "deleted": 0,
        "eligible": 0,
        "failed": True,
        "errors": ["query failed"],
    }

    rc = cli.main(["--semantic-cache", "--execute"])

    assert rc == 1
    body = json.loads(capsys.readouterr().out)
    assert body["ok"] is False
    assert body["results"][0]["failed"] is True


def test_retention_jobs_cli_runs_semantic_cache_for_all_tenants(
    capsys: pytest.CaptureFixture[str],
    runtime_deps: SimpleNamespace,
) -> None:
    tenant_ids = [uuid.uuid4(), uuid.uuid4()]
    calls: list[dict[str, object]] = []

    class _TenantRow:
        def __init__(self, tenant_id: uuid.UUID) -> None:
            self.id = tenant_id

    class _TenantQuery:
        def all(self) -> list[_TenantRow]:
            return [_TenantRow(tenant_id) for tenant_id in tenant_ids]

    class _FakeSession:
        def query(self, _column: object) -> _TenantQuery:
            return _TenantQuery()

        def close(self) -> None:
            return None

    runtime_deps.SessionLocal = lambda: _FakeSession()
    runtime_deps.run_semantic_cache_retention = (
        lambda **kwargs: calls.append(kwargs)
        or {"job": "semantic-cache", "tenant_id": str(kwargs["tenant_id"]), "deleted": 1, "eligible": 1, "failed": False}
    )

    rc = cli.main(["--semantic-cache", "--all-tenants", "--execute", "--max-delete", "5", "--max-scan", "12"])

    assert rc == 0
    assert calls == [
        {"tenant_id": tenant_ids[0], "dry_run": False, "max_delete": 5, "max_scan": 12},
        {"tenant_id": tenant_ids[1], "dry_run": False, "max_delete": 5, "max_scan": 12},
    ]
    body = json.loads(capsys.readouterr().out)
    assert [item["tenant_id"] for item in body["results"]] == [str(tenant_id) for tenant_id in tenant_ids]


def test_retention_jobs_cli_runs_db_backed_audit_retention(
    capsys: pytest.CaptureFixture[str],
    runtime_deps: SimpleNamespace,
) -> None:
    tenant_id = uuid.uuid4()
    calls: list[tuple[object, dict[str, object]]] = []

    class _FakeSession:
        closed = False

        def close(self) -> None:
            self.closed = True

    session = _FakeSession()
    runtime_deps.SessionLocal = lambda: session
    runtime_deps.run_audit_log_retention = (
        lambda db, **kwargs: calls.append((db, kwargs))
        or {"job": "audit-log-retention", "deleted": 0, "eligible": 2, "failed": False}
    )

    rc = cli.main(
        [
            "--audit-logs",
            "--dry-run",
            "--tenant-id",
            str(tenant_id),
            "--retention-days",
            "30",
            "--max-delete",
            "7",
        ]
    )

    assert rc == 0
    assert len(calls) == 1
    assert calls[0][0] is session
    assert calls[0][1]["tenant_id"] == tenant_id
    assert calls[0][1]["retention_days"] == 30
    assert calls[0][1]["max_delete"] == 7
    assert calls[0][1]["dry_run"] is True
    assert session.closed is True
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_retention_jobs_cli_runs_dataset_retention(
    capsys: pytest.CaptureFixture[str],
    runtime_deps: SimpleNamespace,
) -> None:
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    policy = SimpleNamespace(enabled=True)
    calls: list[dict[str, object]] = []

    class _Column:
        def __eq__(self, _other: object) -> "_Column":
            return self

        def asc(self) -> "_Column":
            return self

    class _DatasetQuery:
        def filter(self, *_conditions: object) -> "_DatasetQuery":
            return self

        def order_by(self, *_columns: object) -> "_DatasetQuery":
            return self

        def all(self) -> list[tuple[uuid.UUID, dict[str, object]]]:
            return [(dataset_id, {"retention": {"enabled": True}})]

    class _FakeSession:
        closed = False

        def query(self, *_columns: object) -> _DatasetQuery:
            return _DatasetQuery()

        def close(self) -> None:
            self.closed = True

    async def _run_dataset_retention_sweep(_db: object, **kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"job": "dataset-retention", "deleted": 0, "eligible": 1, "failed": False}

    session = _FakeSession()
    column = _Column()
    runtime_deps.SessionLocal = lambda: session
    runtime_deps.Dataset = SimpleNamespace(id=column, dataset_metadata=column, tenant_id=column, created_at=column)
    runtime_deps.parse_retention_policy_from_metadata = lambda _metadata: policy
    runtime_deps.run_dataset_retention_sweep = _run_dataset_retention_sweep

    rc = cli.main(
        [
            "--dataset-retention",
            "--dry-run",
            "--tenant-id",
            str(tenant_id),
            "--dataset-id",
            str(dataset_id),
            "--max-documents",
            "17",
            "--max-versions-pruned",
            "3",
        ]
    )

    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["tenant_id"] == tenant_id
    assert calls[0]["dataset_id"] == dataset_id
    assert calls[0]["policy"] is policy
    assert calls[0]["max_documents"] == 17
    assert calls[0]["max_versions_pruned"] == 3
    assert calls[0]["dry_run"] is True
    assert session.closed is True
    assert json.loads(capsys.readouterr().out)["ok"] is True
