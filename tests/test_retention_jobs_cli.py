import json
import uuid

import pytest


def test_retention_jobs_cli_runs_semantic_cache_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.run_retention_jobs as cli

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
    import scripts.run_retention_jobs as cli

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
    import scripts.run_retention_jobs as cli

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
