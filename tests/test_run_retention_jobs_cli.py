from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

from scripts import run_retention_jobs


class _FakeDB:
    def close(self) -> None:
        return


def test_run_retention_jobs_supports_knowledge_assets(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    tenant_id = uuid4()
    captured: list[dict] = []

    monkeypatch.setattr(run_retention_jobs, "SessionLocal", lambda: _FakeDB(), raising=True)

    async def _fake_job(db, **kwargs):  # noqa: ANN001
        await asyncio.sleep(0)  # Sonar S7503
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
