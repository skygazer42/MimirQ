import logging
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest


@pytest.mark.parametrize("operation", ["purge", "delete", "export", "summary", "evidence", "evaluations"])
def test_api_audit_commit_failure_is_observable(operation, monkeypatch, caplog):
    from app.api.v1 import audit, evaluations, evidence

    db = MagicMock()
    failure = RuntimeError("audit commit failed")
    db.commit.side_effect = failure
    db.query.return_value.filter.return_value.count.return_value = 0
    monkeypatch.setattr(audit, "ensure_tenant_permission", lambda *a, **k: None)
    monkeypatch.setattr(audit, "_ensure_admin", lambda *a: None)
    monkeypatch.setattr(audit, "plan_audit_log_purge", lambda *a, **k: 0)
    monkeypatch.setattr(audit, "delete_audit_log_rows", lambda *a, **k: 1)
    monkeypatch.setattr(evaluations, "ensure_tenant_permission", lambda *a, **k: None)
    monkeypatch.setattr(evaluations, "plan_regression_run_purge", lambda *a, **k: 0)
    args = dict(db=db, tenant_id=uuid4(), account_id="owner")
    with caplog.at_level(logging.WARNING):
        if operation == "purge":
            audit.purge_audit_logs(audit.audit_log_purge_params(), audit.audit_log_filter_params(), **args)
        elif operation == "delete":
            audit._delete_audit_logs_by_id(**args, ids=[uuid4()], action="audit.logs.delete")
        elif operation == "export":
            audit._audit_access_graph_export(
                **args,
                limit=10,
                returned=0,
                after_kind=None,
                after_created_at=None,
                after_id=None,
                include_sensitive=False,
                export_format="json",
                gzip_enabled=False,
            )
        elif operation == "summary":
            audit.access_graph_summary(**args)
        elif operation == "evidence":
            evidence._audit_reference_repair_enqueue(
                **args, suite_id=uuid4(), task_id="task", payload=evidence.EvidenceReferenceRepairRequest()
            )
        else:
            evaluations.purge_ragas_regression_runs(**args)
    db.rollback.assert_called_once()
    assert any(r.exc_info and r.exc_info[1] is failure for r in caplog.records)


def test_profile_enqueue_compensation_failure_is_observable(caplog):
    from app.api.v1.datasets import _mark_dataset_profile_scan_run_failed

    db = MagicMock()
    failure = RuntimeError("profile compensation commit failed")
    db.commit.side_effect = failure
    with caplog.at_level(logging.WARNING):
        _mark_dataset_profile_scan_run_failed(db, row=SimpleNamespace(id=uuid4()), error_message="queue failed")
    db.rollback.assert_called_once()
    assert any(r.exc_info and r.exc_info[1] is failure for r in caplog.records)


@pytest.mark.parametrize("kind", ["profile", "precheck"])
@pytest.mark.parametrize("compensation_fails", [False, True])
def test_background_scan_failure_is_logged_and_session_recovered(kind, compensation_fails, monkeypatch, caplog):
    from app.api.v1 import dataset_precheck, datasets
    from app.tasks import queue

    module = datasets if kind == "profile" else dataset_precheck
    runner = "run_dataset_profile_deep_scan" if kind == "profile" else "run_dataset_precheck_scan"
    entry = module._run_deep_scan_background if kind == "profile" else module._run_precheck_scan_background
    failure = RuntimeError("scan transaction failed")
    db = MagicMock()
    row = SimpleNamespace(id=uuid4())
    db.query.return_value.filter.return_value.first.return_value = row
    if compensation_fails:
        db.commit.side_effect = RuntimeError("failed-state commit failed")
    monkeypatch.setattr(module, "SessionLocal", lambda: db)
    monkeypatch.setattr(module, runner, MagicMock(side_effect=failure))
    monkeypatch.setattr(queue, "register_local_scan_run_active", lambda **k: None)
    monkeypatch.setattr(queue, "unregister_local_scan_run_active", lambda **k: None)
    args = dict(tenant_id=uuid4(), dataset_id=uuid4(), scan_run_id=row.id)
    if kind == "profile":
        args["account_id"] = "owner"
    with caplog.at_level(logging.WARNING):
        entry(**args)
    assert db.rollback.call_count >= 1
    assert any(r.exc_info and r.exc_info[1] is failure for r in caplog.records)
    assert row.status == "failed"
    db.close.assert_called_once()
