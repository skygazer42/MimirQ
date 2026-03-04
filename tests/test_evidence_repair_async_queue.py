from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException, Response


class _FakeSuite:
    def __init__(self, *, suite_id: UUID, dataset_id: UUID):
        self.id = suite_id
        self.dataset_id = dataset_id


class _FakeQuery:
    def __init__(self, kind: str, suite: _FakeSuite | None):
        self._kind = kind
        self._suite = suite

    def filter(self, *args, **kwargs):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN201
        if self._kind == "suite":
            return self._suite
        return None

    def order_by(self, *args, **kwargs):  # noqa: ANN001
        return self

    def limit(self, *args, **kwargs):  # noqa: ANN001
        return self

    def all(self):  # noqa: ANN201
        return []


class _FakeSession:
    def __init__(self, suite: _FakeSuite | None):
        self._suite = suite

    def query(self, model):  # noqa: ANN001
        name = getattr(model, "__name__", "")
        if name == "EvidenceSuite":
            return _FakeQuery("suite", self._suite)
        return _FakeQuery("other", self._suite)

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


@pytest.mark.asyncio
async def test_evidence_repair_async_requires_queue_enabled(monkeypatch):
    from app.api.v1.evidence import repair_evidence_suite_reference_sources
    from app.core import config as config_mod
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    suite_id = UUID(int=1)
    dataset_id = UUID(int=2)
    db = _FakeSession(_FakeSuite(suite_id=suite_id, dataset_id=dataset_id))

    from app.api.schemas.evidence_repair import EvidenceReferenceRepairRequest

    with pytest.raises(HTTPException) as exc:
        await repair_evidence_suite_reference_sources(
            suite_id=suite_id,
            payload=EvidenceReferenceRepairRequest(apply=True),
            async_mode=True,
            tenant_id=UUID(int=3),
            account_id="u",
            response=Response(),
            db=db,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_evidence_repair_async_enqueues_and_returns_202(monkeypatch):
    from app.api.v1.evidence import repair_evidence_suite_reference_sources
    from app.core import config as config_mod
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    async def _fake_enqueue(  # noqa: ANN001
        *,
        tenant_id,
        suite_id,
        requested_by,
        job_id=None,
        apply=None,
        allow_approved=None,
        include_archived_items=None,
        max_items=None,
        max_refs_per_item=None,
        max_changes=None,
    ):
        assert requested_by == "u"
        assert job_id and job_id.startswith("evidence_repair:")
        assert apply is True
        assert allow_approved is False
        assert include_archived_items is False
        assert int(max_items) == 5000
        assert int(max_refs_per_item) == 50
        assert int(max_changes) == 500
        return "task-1"

    import app.tasks.queue as queue_mod

    monkeypatch.setattr(queue_mod, "enqueue_evidence_reference_sources_repair", _fake_enqueue, raising=True)

    suite_id = UUID(int=1)
    dataset_id = UUID(int=2)
    db = _FakeSession(_FakeSuite(suite_id=suite_id, dataset_id=dataset_id))

    from app.api.schemas.evidence_repair import EvidenceReferenceRepairRequest

    resp = Response()
    out = await repair_evidence_suite_reference_sources(
        suite_id=suite_id,
        payload=EvidenceReferenceRepairRequest(apply=True),
        async_mode=True,
        tenant_id=UUID(int=3),
        account_id="u",
        response=resp,
        db=db,
    )

    assert resp.status_code == 202
    assert resp.headers.get("X-Task-Id") == "task-1"
    assert out.suite_id == suite_id
    assert out.dataset_id == dataset_id
    assert out.applied is True
    assert out.scanned_items == 0
    assert out.repaired_references == 0

