from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


class _DummyQuery:
    def __init__(self, result):  # noqa: ANN001
        self._result = result

    def filter(self, *args, **kwargs):  # noqa: ANN001,ANN202
        return self

    def order_by(self, *args, **kwargs):  # noqa: ANN001,ANN202
        return self

    def offset(self, *args, **kwargs):  # noqa: ANN001,ANN202
        return self

    def limit(self, *args, **kwargs):  # noqa: ANN001,ANN202
        return self

    def first(self):  # noqa: ANN202
        return self._result

    def all(self):  # noqa: ANN202
        if self._result is None:
            return []
        return [self._result]

    def count(self) -> int:
        return 1 if self._result is not None else 0


class _DummyDB:
    def __init__(self, results):  # noqa: ANN001
        self._results = list(results)
        self._commits = 0

    def query(self, _model):  # noqa: ANN001,ANN202
        if not self._results:
            return _DummyQuery(None)
        return _DummyQuery(self._results.pop(0))

    def add(self, obj) -> None:  # noqa: ANN001
        return None

    def commit(self) -> None:
        self._commits += 1

    def refresh(self, obj) -> None:  # noqa: ANN001
        return None


def test_precheck_cancel_endpoint(monkeypatch):  # noqa: ANN001
    from app.api.v1.dataset_precheck import cancel_dataset_precheck_scan_run

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()

    run = SimpleNamespace(
        id=run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        kind="path",
        status="running",
        progress=10,
        config={},
        summary={},
        artifacts={},
    )

    # Bypass dataset permission checks.
    monkeypatch.setattr("app.api.v1.dataset_precheck.get_dataset_for_precheck", lambda *_a, **_k: object(), raising=True)

    db = _DummyDB([run])
    out = cancel_dataset_precheck_scan_run(dataset_id=dataset_id, scan_run_id=run_id, tenant_id=tenant_id, account_id="u", db=db)
    assert out.status == "cancelled"


def test_precheck_samples_endpoint(monkeypatch):  # noqa: ANN001
    from app.api.v1.dataset_precheck import get_dataset_precheck_samples

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()

    run = SimpleNamespace(id=run_id, tenant_id=tenant_id, dataset_id=dataset_id, status="completed", config={}, artifacts={})

    monkeypatch.setattr("app.api.v1.dataset_precheck.get_dataset_for_precheck", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(
        "app.api.v1.dataset_precheck.load_precheck_samples_from_row",
        lambda *_a, **_k: {"requested": 1, "strata_count": 1, "representative": [], "needs_review": {}, "top_large_files": [], "top_long_text": []},
        raising=True,
    )

    db = _DummyDB([run])
    out = get_dataset_precheck_samples(dataset_id=dataset_id, scan_run_id=run_id, size=1, prefer_artifact=True, tenant_id=tenant_id, account_id="u", db=db)
    assert out.requested == 1
    assert out.strata_count == 1


def test_precheck_samples_endpoint_merges_review_metadata(monkeypatch):  # noqa: ANN001
    from app.api.v1.dataset_precheck import get_dataset_precheck_samples

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()

    run = SimpleNamespace(id=run_id, tenant_id=tenant_id, dataset_id=dataset_id, status="completed", config={}, artifacts={})

    monkeypatch.setattr("app.api.v1.dataset_precheck.get_dataset_for_precheck", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(
        "app.api.v1.dataset_precheck.load_precheck_samples_from_row",
        lambda *_a, **_k: {
            "requested": 1,
            "strata_count": 1,
            "representative": [{"name": "报价单.pdf", "file_type": "pdf", "file_size": 12}],
            "needs_review": {},
            "top_large_files": [],
            "top_long_text": [],
        },
        raising=True,
    )
    monkeypatch.setattr(
        "app.api.v1.dataset_precheck.load_precheck_sample_reviews_from_row",
        lambda *_a, **_k: {
            "报价单.pdf": {
                "review_disposition": "approved",
                "reviewed_at": "2026-05-13T00:00:00Z",
                "reviewed_by": "u",
            }
        },
        raising=True,
    )

    db = _DummyDB([run])
    out = get_dataset_precheck_samples(dataset_id=dataset_id, scan_run_id=run_id, size=1, prefer_artifact=True, tenant_id=tenant_id, account_id="u", db=db)
    assert out.representative[0].review_disposition == "approved"
    assert str(out.representative[0].reviewed_by) == "u"


def test_precheck_patch_sample_review_endpoint(monkeypatch):  # noqa: ANN001
    from app.api.schemas.dataset_precheck import DatasetPrecheckSampleReviewPatchRequest
    from app.api.v1.dataset_precheck import patch_dataset_precheck_sample_review

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()

    run = SimpleNamespace(id=run_id, tenant_id=tenant_id, dataset_id=dataset_id, status="completed", config={}, artifacts={})

    monkeypatch.setattr("app.api.v1.dataset_precheck.get_dataset_for_precheck", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(
        "app.api.v1.dataset_precheck.load_precheck_samples_from_row",
        lambda *_a, **_k: {
            "requested": 1,
            "strata_count": 1,
            "representative": [{"name": "报价单.pdf", "file_type": "pdf", "file_size": 12}],
            "needs_review": {},
            "top_large_files": [],
            "top_long_text": [],
        },
        raising=True,
    )
    monkeypatch.setattr(
        "app.api.v1.dataset_precheck.upsert_precheck_sample_review_for_row",
        lambda *_a, **_k: {
            "review_disposition": "manual",
            "reviewed_at": "2026-05-13T00:00:00Z",
            "reviewed_by": "u",
        },
        raising=True,
    )

    db = _DummyDB([run])
    out = patch_dataset_precheck_sample_review(
        dataset_id=dataset_id,
        scan_run_id=run_id,
        body=DatasetPrecheckSampleReviewPatchRequest(
            file_name="报价单.pdf",
            disposition="manual",
        ),
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )
    assert out.file_name == "报价单.pdf"
    assert out.review_disposition == "manual"


def test_precheck_suggest_and_apply_ingestion_policy_endpoints(monkeypatch):  # noqa: ANN001
    from app.api.v1.dataset_precheck import (
        apply_dataset_precheck_ingestion_policy_suggestion,
        get_dataset_precheck_ingestion_policy_suggestion,
    )

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()

    run = SimpleNamespace(id=run_id, tenant_id=tenant_id, dataset_id=dataset_id, summary={"x": 1}, artifacts={}, config={})

    monkeypatch.setattr("app.api.v1.dataset_precheck.get_dataset_for_precheck", lambda *_a, **_k: SimpleNamespace(dataset_metadata={}), raising=True)
    monkeypatch.setattr(
        "app.api.v1.dataset_precheck.build_ingestion_policy_suggestion",
        lambda *_a, **_k: {
            "generated_at": "2026-01-01T00:00:00Z",
            "policy": {"version": "1", "rules": []},
            "notes": [],
            "manual_review": [],
        },
        raising=True,
    )
    monkeypatch.setattr(
        "app.api.v1.dataset_precheck.apply_ingestion_policy_suggestion",
        lambda *_a, **_k: {"replaced": True, "rule_count": 0},
        raising=True,
    )

    db = _DummyDB([run])
    suggest = get_dataset_precheck_ingestion_policy_suggestion(
        dataset_id=dataset_id,
        scan_run_id=run_id,
        max_names_per_bucket=10,
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )
    assert suggest.policy.version == "1"

    db2 = _DummyDB([run])
    applied = apply_dataset_precheck_ingestion_policy_suggestion(
        dataset_id=dataset_id,
        scan_run_id=run_id,
        replace=False,
        tenant_id=tenant_id,
        account_id="u",
        db=db2,
    )
    assert applied.rule_count == 0


def test_precheck_diff_endpoint(monkeypatch):  # noqa: ANN001
    from app.api.v1.dataset_precheck import diff_dataset_precheck_scan_runs

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    base_id = uuid.uuid4()
    target_id = uuid.uuid4()

    base = SimpleNamespace(id=base_id, tenant_id=tenant_id, dataset_id=dataset_id, summary={"total_files": 1}, artifacts={}, config={})
    target = SimpleNamespace(id=target_id, tenant_id=tenant_id, dataset_id=dataset_id, summary={"total_files": 2}, artifacts={}, config={})

    monkeypatch.setattr("app.api.v1.dataset_precheck.get_dataset_for_precheck", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(
        "app.api.v1.dataset_precheck.diff_precheck_summaries",
        lambda *_a, **_k: {
            "base_scan_run_id": str(base_id),
            "target_scan_run_id": str(target_id),
            "generated_at": "2026-01-01T00:00:00Z",
            "total_files": {"key": "total_files", "before": 1, "after": 2, "delta": 1},
            "total_size_bytes": {"key": "total_size_bytes", "before": 0, "after": 0, "delta": 0},
            "pdf_scanned": {"key": "pdf_scanned", "before": 0, "after": 0, "delta": 0},
            "pdf_unknown": {"key": "pdf_unknown", "before": 0, "after": 0, "delta": 0},
            "by_file_type": [],
            "findings": [],
        },
        raising=True,
    )

    db = _DummyDB([base, target])
    out = diff_dataset_precheck_scan_runs(
        dataset_id=dataset_id,
        scan_run_id=target_id,
        base_scan_run_id=base_id,
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )
    assert out.total_files.delta == 1


def test_precheck_diff_endpoint_missing_summary_404(monkeypatch):  # noqa: ANN001
    from app.api.v1.dataset_precheck import diff_dataset_precheck_scan_runs

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    base_id = uuid.uuid4()
    target_id = uuid.uuid4()

    base = SimpleNamespace(id=base_id, tenant_id=tenant_id, dataset_id=dataset_id, summary={}, artifacts={}, config={})
    target = SimpleNamespace(id=target_id, tenant_id=tenant_id, dataset_id=dataset_id, summary={}, artifacts={}, config={})

    monkeypatch.setattr("app.api.v1.dataset_precheck.get_dataset_for_precheck", lambda *_a, **_k: object(), raising=True)
    db = _DummyDB([base, target])
    with pytest.raises(HTTPException) as exc:
        diff_dataset_precheck_scan_runs(
            dataset_id=dataset_id,
            scan_run_id=target_id,
            base_scan_run_id=base_id,
            tenant_id=tenant_id,
            account_id="u",
            db=db,
        )
    assert exc.value.status_code == 404
