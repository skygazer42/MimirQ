import json
import uuid
from types import SimpleNamespace

import pytest

import scripts.run_retention_jobs as cli


def test_retention_jobs_cli_runs_semantic_cache_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tenant_id = uuid.uuid4()
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli,
        "run_semantic_cache_retention",
        lambda **kwargs: calls.append(kwargs) or {"job": "semantic-cache", "deleted": 0, "eligible": 3, "failed": False},
        raising=True,
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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    default_tenant = uuid.uuid4()
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(cli.settings, "DEFAULT_TENANT_ID", str(default_tenant), raising=False)
    monkeypatch.setattr(
        cli,
        "run_semantic_cache_retention",
        lambda **kwargs: calls.append(kwargs) or {"job": "semantic-cache", "deleted": 2, "eligible": 2, "failed": False},
        raising=True,
    )

    rc = cli.main(["--semantic-cache", "--execute", "--max-delete", "9", "--max-scan", "15"])

    assert rc == 0
    assert calls == [{"tenant_id": default_tenant, "dry_run": False, "max_delete": 9, "max_scan": 15}]
    body = json.loads(capsys.readouterr().out)
    assert body["results"][0]["deleted"] == 2


def test_retention_jobs_cli_returns_nonzero_on_semantic_cache_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "run_semantic_cache_retention",
        lambda **_kwargs: {"job": "semantic-cache", "deleted": 0, "eligible": 0, "failed": True, "errors": ["query failed"]},
        raising=True,
    )

    rc = cli.main(["--semantic-cache", "--execute"])

    assert rc == 1
    body = json.loads(capsys.readouterr().out)
    assert body["ok"] is False
    assert body["results"][0]["failed"] is True


def test_retention_jobs_cli_runs_semantic_cache_for_all_tenants(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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

    monkeypatch.setattr(cli, "SessionLocal", lambda: _FakeSession(), raising=True)
    monkeypatch.setattr(cli, "Tenant", SimpleNamespace(id=object()), raising=True)
    monkeypatch.setattr(
        cli,
        "run_semantic_cache_retention",
        lambda **kwargs: calls.append(kwargs)
        or {"job": "semantic-cache", "tenant_id": str(kwargs["tenant_id"]), "deleted": 1, "eligible": 1, "failed": False},
        raising=True,
    )

    rc = cli.main(["--semantic-cache", "--all-tenants", "--execute", "--max-delete", "5", "--max-scan", "12"])

    assert rc == 0
    assert calls == [
        {"tenant_id": tenant_ids[0], "dry_run": False, "max_delete": 5, "max_scan": 12},
        {"tenant_id": tenant_ids[1], "dry_run": False, "max_delete": 5, "max_scan": 12},
    ]
    body = json.loads(capsys.readouterr().out)
    assert [item["tenant_id"] for item in body["results"]] == [str(tenant_id) for tenant_id in tenant_ids]
