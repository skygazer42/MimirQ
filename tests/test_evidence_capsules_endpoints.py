from __future__ import annotations

import uuid

import pytest


def test_evidence_capsules_persist_and_get(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    from app.api.v1 import evidence_capsules as mod
    from app.rag.core.evidence_capsule_builder import build_evidence_capsule

    monkeypatch.setattr(mod.settings, "EVIDENCE_CAPSULE_PERSIST_ENABLED", True, raising=False)
    monkeypatch.setattr(mod.settings, "EVIDENCE_CAPSULE_STORE_DIR", str(tmp_path / "capsules"), raising=False)
    monkeypatch.setattr(mod.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    capsule = build_evidence_capsule(
        query_for_retrieval="q",
        citations=[{"document_id": "d1", "chunk_id": "c1"}],
        metrics={"retrieval_mode": "hybrid"},
        retrieval_trace=None,
    )

    created = mod.persist_evidence_capsule(
        body=mod.EvidenceCapsulePersistRequest(capsule=capsule),
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )
    assert created.capsule_id
    assert created.capsule_hash == str(capsule.get("capsule_hash") or "")

    loaded = mod.get_evidence_capsule(
        capsule_id=created.capsule_id,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )
    assert loaded.capsule_id == created.capsule_id
    assert str(loaded.capsule.get("capsule_hash") or "") == created.capsule_hash
