import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from scripts import run_db_maintenance_jobs as jobs

TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")


class _Session:
    def __init__(self, *, query_error: Exception | None = None) -> None:
        self.query_error = query_error
        self.closed = False

    def query(self, _field: object) -> "_Session":
        if self.query_error is not None:
            raise self.query_error
        return self

    def all(self) -> list[tuple[UUID]]:
        return [(TENANT_ID,)]

    def close(self) -> None:
        self.closed = True


def _json_output(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    return json.loads(capsys.readouterr().out)


def test_main_requires_at_least_one_job(capsys: pytest.CaptureFixture[str]) -> None:
    assert jobs.main([]) == 2
    assert "No job selected" in capsys.readouterr().err


def test_main_runs_selected_global_and_tenant_jobs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = _Session()
    calls: list[tuple[str, dict[str, Any]]] = []

    def run_postgres_maintenance(**kwargs: Any) -> dict[str, Any]:
        calls.append(("postgres", kwargs))
        return {"ok": True, "statements": ["VACUUM"]}

    def run_audit_log_retention(_db: object, **kwargs: Any) -> dict[str, Any]:
        calls.append(("audit", kwargs))
        return {"deleted": 3}

    def run_regression_run_retention(_db: object, **kwargs: Any) -> dict[str, Any]:
        calls.append(("regression", kwargs))
        return {"deleted": 2}

    monkeypatch.setattr(jobs, "SessionLocal", lambda: session)
    monkeypatch.setattr(jobs, "run_postgres_maintenance", run_postgres_maintenance)
    monkeypatch.setattr(jobs, "run_audit_log_retention", run_audit_log_retention)
    monkeypatch.setattr(jobs, "run_regression_run_retention", run_regression_run_retention)

    result = jobs.main(
        [
            "--vacuum",
            "--audit-logs",
            "--regression-runs",
            "--tenant-id",
            str(TENANT_ID),
            "--execute",
            "--retention-days",
            "12",
            "--max-delete",
            "7",
            "--table",
            " public.events ",
        ]
    )

    assert result == 0
    assert session.closed is True
    payload = _json_output(capsys)
    assert payload["ok"] is True
    assert payload["results"] == [
        {"ok": True, "statements": ["VACUUM"], "job": "postgres_maintenance"},
        {"job": "audit_logs_retention", "ok": True, "deleted": 3},
        {"job": "regression_runs_retention", "ok": True, "deleted": 2},
    ]
    assert [name for name, _kwargs in calls] == ["postgres", "audit", "regression"]
    assert calls[0][1]["tables"] == [" public.events "]
    assert calls[0][1]["dry_run"] is False
    for _name, kwargs in calls[1:]:
        assert kwargs["tenant_id"] == TENANT_ID
        assert kwargs["retention_days"] == 12
        assert kwargs["max_delete"] == 7
        assert kwargs["dry_run"] is False
        assert kwargs["now"] == calls[0][1]["now"]


def test_main_reports_all_tenant_lookup_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = _Session(query_error=RuntimeError("database offline"))
    monkeypatch.setattr(jobs, "SessionLocal", lambda: session)
    monkeypatch.setattr(jobs, "Tenant", SimpleNamespace(id=object()))
    monkeypatch.setattr(
        jobs,
        "run_audit_log_retention",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retention must not run")),
    )

    assert jobs.main(["--audit-logs", "--all-tenants"]) == 1

    assert session.closed is True
    assert _json_output(capsys)["results"] == [
        {
            "job": "tenant_list",
            "ok": False,
            "error": "RuntimeError",
            "detail": "database offline",
        }
    ]
