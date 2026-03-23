from __future__ import annotations

import json
from uuid import uuid4

import pytest

from scripts import run_retention_jobs
from tests.helpers.async_utils import yield_control


class _FakeDB:
    def close(self) -> None:
        return


def test_run_retention_jobs_supports_knowledge_assets(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    tenant_id = uuid4()
    captured: list[dict] = []

    monkeypatch.setattr(run_retention_jobs, "SessionLocal", lambda: _FakeDB(), raising=True)

    async def _fake_job(db, **kwargs):  # noqa: ANN001
        await yield_control()
        assert db is not None
        captured.append(dict(kwargs))
        return {
            "tenant_id": str(kwargs["tenant_id"]),
            "dry_run": bool(kwargs["dry_run"]),
            "eligible": 3,
            "deleted": 0,
        }

    monkeypatch.setattr(run_retention_jobs, "run_knowledge_asset_retention", _fake_job, raising=False)

    try:
        rc = run_retention_jobs.main(
            [
                "--knowledge-assets",
                "--tenant-id",
                str(tenant_id),
                "--dry-run",
                "--retention-days",
                "45",
                "--max-delete",
                "25",
            ]
        )
    except SystemExit as exc:
        pytest.fail(f"run_retention_jobs should accept --knowledge-assets (SystemExit={exc.code})")

    assert rc == 0
    assert len(captured) == 1
    assert captured[0]["tenant_id"] == tenant_id
    assert captured[0]["dry_run"] is True
    assert captured[0]["retention_days"] == 45
    assert captured[0]["max_delete"] == 25

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["results"][0]["eligible"] == 3


def test_run_retention_jobs_supports_dataset_retention(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    captured: list[dict] = []

    class _DatasetQuery:
        def filter(self, *_args, **_kwargs):  # noqa: ANN001, ANN201
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN001, ANN201
            return self

        def all(self):  # noqa: ANN201
            return [
                (
                    dataset_id,
                    {
                        "retention_policy": {
                            "enabled": True,
                            "action": "archive",
                            "max_age_days": 30,
                            "max_versions": 2,
                        }
                    },
                )
            ]

    class _DatasetRetentionDB(_FakeDB):
        def query(self, *_args, **_kwargs):  # noqa: ANN001, ANN201
            return _DatasetQuery()

    monkeypatch.setattr(run_retention_jobs, "SessionLocal", lambda: _DatasetRetentionDB(), raising=True)

    async def _fake_job(db, **kwargs):  # noqa: ANN001
        await yield_control()
        assert db is not None
        captured.append(dict(kwargs))
        return {
            "tenant_id": str(kwargs["tenant_id"]),
            "dataset_id": str(kwargs["dataset_id"]),
            "dry_run": bool(kwargs["dry_run"]),
            "documents": {"eligible": 2},
        }

    monkeypatch.setattr(run_retention_jobs, "run_dataset_retention_sweep", _fake_job, raising=False)

    try:
        rc = run_retention_jobs.main(
            [
                "--dataset-retention",
                "--tenant-id",
                str(tenant_id),
                "--dataset-id",
                str(dataset_id),
                "--dry-run",
                "--max-documents",
                "12",
                "--max-versions-pruned",
                "3",
            ]
        )
    except SystemExit as exc:
        pytest.fail(f"run_retention_jobs should accept --dataset-retention (SystemExit={exc.code})")

    assert rc == 0
    assert len(captured) == 1
    assert captured[0]["tenant_id"] == tenant_id
    assert captured[0]["dataset_id"] == dataset_id
    assert captured[0]["dry_run"] is True
    assert captured[0]["max_documents"] == 12
    assert captured[0]["max_versions_pruned"] == 3
    assert captured[0]["policy"].enabled is True
    assert captured[0]["policy"].max_age_days == 30

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["results"][0]["documents"]["eligible"] == 2
