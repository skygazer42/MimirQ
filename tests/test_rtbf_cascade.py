from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from tests.helpers.async_utils import yield_control


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_run_rtbf_cascade_dry_run_reports_candidates_without_deleting(monkeypatch):  # noqa: ANN001
    from app.services import rtbf_cascade

    db = _FakeDB()
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)

    candidates = [
        {
            "document_id": uuid.uuid4(),
            "dataset_id": dataset_id,
            "owner_id": "acct-1",
            "filename": "a.pdf",
            "match_reasons": ["owner_id"],
        },
        {
            "document_id": uuid.uuid4(),
            "dataset_id": None,
            "owner_id": "acct-1",
            "filename": "b.md",
            "match_reasons": ["lifecycle_owner"],
        },
    ]

    monkeypatch.setattr(rtbf_cascade, "_list_rtbf_documents", lambda *_a, **_k: list(candidates), raising=True)

    async def _fail_delete(**_kwargs):  # noqa: ANN001
        await yield_control()
        raise AssertionError("dry-run must not invoke delete lifecycle")

    monkeypatch.setattr(rtbf_cascade, "_resolve_delete_document_lifecycle", lambda: _fail_delete, raising=True)
    monkeypatch.setattr(
        rtbf_cascade,
        "invalidate_dataset_cache_namespace",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("dry-run must not invalidate cache")),
        raising=True,
    )

    captured: list[dict] = []

    def _audit(_db, **kwargs):  # noqa: ANN001
        captured.append(kwargs)

    monkeypatch.setattr(rtbf_cascade, "audit_log_event", _audit, raising=True)

    out = asyncio.run(
        rtbf_cascade.run_rtbf_cascade(
            db,
            tenant_id=tenant_id,
            subject_account_id="acct-1",
            dry_run=True,
            actor_id="system:test",
            now=now,
        )
    )

    assert out["schema"] == "mimirq.rtbf_cascade.v1"
    assert out["dry_run"] is True
    assert out["eligible"] == 2
    assert out["deleted"] == 0
    assert out["errors"] == 0
    assert out["cache_invalidations"] == 0
    assert out["artifact_scopes"] == ["documents", "chunks", "kg", "vectors", "object_assets", "cache"]
    assert len(out["documents"]) == 2
    assert out["documents"][0]["match_reasons"] == ["owner_id"]
    assert len(captured) == 1
    assert captured[0]["action"] == "privacy.rtbf.cascade"
    assert db.commits == 1


def test_run_rtbf_cascade_execute_retries_delete_and_invalidates_unique_datasets(monkeypatch):  # noqa: ANN001
    from app.services import rtbf_cascade

    db = _FakeDB()
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime(2026, 4, 24, 12, 30, tzinfo=UTC)

    doc1 = uuid.uuid4()
    doc2 = uuid.uuid4()
    candidates = [
        {
            "document_id": doc1,
            "dataset_id": dataset_id,
            "owner_id": "acct-1",
            "filename": "a.pdf",
            "match_reasons": ["owner_id"],
        },
        {
            "document_id": doc2,
            "dataset_id": dataset_id,
            "owner_id": "acct-1",
            "filename": "b.pdf",
            "match_reasons": ["owner_id"],
        },
    ]

    monkeypatch.setattr(rtbf_cascade, "_list_rtbf_documents", lambda *_a, **_k: list(candidates), raising=True)

    attempts: dict[uuid.UUID, int] = {}
    deleted: list[uuid.UUID] = []

    async def _delete_document_lifecycle(*, document_id, tenant_id, account_id, db, enforce_permissions):  # noqa: ANN001
        await yield_control()
        assert tenant_id
        assert account_id == "system:test"
        assert enforce_permissions is False
        attempts[document_id] = int(attempts.get(document_id, 0) or 0) + 1
        if document_id == doc1 and attempts[document_id] == 1:
            raise RuntimeError("temporary delete failure")
        deleted.append(document_id)
        return None

    monkeypatch.setattr(rtbf_cascade, "_resolve_delete_document_lifecycle", lambda: _delete_document_lifecycle, raising=True)

    invalidations: list[tuple[uuid.UUID, uuid.UUID]] = []

    def _invalidate(db_arg, *, tenant_id, dataset_id):  # noqa: ANN001
        invalidations.append((tenant_id, dataset_id))
        return {"ok": True, "dataset_id": str(dataset_id)}

    monkeypatch.setattr(rtbf_cascade, "invalidate_dataset_cache_namespace", _invalidate, raising=True)
    monkeypatch.setattr(rtbf_cascade, "audit_log_event", lambda *_a, **_k: None, raising=True)

    out = asyncio.run(
        rtbf_cascade.run_rtbf_cascade(
            db,
            tenant_id=tenant_id,
            subject_account_id="acct-1",
            dry_run=False,
            actor_id="system:test",
            max_retries=1,
            now=now,
        )
    )

    assert out["dry_run"] is False
    assert out["eligible"] == 2
    assert out["deleted"] == 2
    assert out["errors"] == 0
    assert out["cache_invalidations"] == 1
    assert attempts[doc1] == 2
    assert attempts[doc2] == 1
    assert deleted == [doc1, doc2]
    assert invalidations == [(tenant_id, dataset_id)]
    assert db.commits == 1
