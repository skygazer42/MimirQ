from __future__ import annotations

from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_ping_job_returns_standardized_result() -> None:
    import app.tasks.jobs as jobs_mod

    out = await jobs_mod.ping_job({})

    assert out["schema"] == "mimirq.task_job_result.v1"
    assert out["job_name"] == "ping_job"
    assert out["ok"] is True
    assert out["reason"] is None
    assert out["progress"]["stage"] == "completed"
    assert out["elapsed_sec"] >= 0


class _MissingQuery:
    def filter(self, *args, **kwargs):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN201
        return None


class _MissingSession:
    def query(self, _model):  # noqa: ANN001
        return _MissingQuery()

    def close(self) -> None:
        return


@pytest.mark.asyncio
async def test_extract_kg_job_missing_document_returns_standardized_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.tasks.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "SessionLocal", lambda: _MissingSession(), raising=True)

    out = await jobs_mod.extract_kg_job(
        ctx={},
        tenant_id=str(UUID(int=3)),
        document_id=str(UUID(int=2)),
        requested_by="u",
    )

    assert out["schema"] == "mimirq.task_job_result.v1"
    assert out["job_name"] == "extract_kg_job"
    assert out["ok"] is False
    assert out["reason"] == "document_not_found"
    assert out["tenant_id"] == str(UUID(int=3))
    assert out["document_id"] == str(UUID(int=2))
    assert out["progress"]["stage"] == "missing"
