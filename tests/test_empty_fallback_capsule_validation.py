from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1 import evidence_capsules


class StorageBoundaryError(Exception):
    pass


@pytest.fixture
def capsule_persistence_boundary(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(evidence_capsules.settings, "EVIDENCE_CAPSULE_PERSIST_ENABLED", True)
    monkeypatch.setattr(evidence_capsules.settings, "EVIDENCE_CAPSULE_STRICT_VALIDATION_ENABLED", False)
    monkeypatch.setattr(evidence_capsules.settings, "EVIDENCE_CAPSULE_VERIFY_HASH_ON_PERSIST", False)
    monkeypatch.setattr(evidence_capsules.settings, "EVIDENCE_CAPSULE_REQUIRE_SIGNATURE_ON_PERSIST", False)
    monkeypatch.setattr(evidence_capsules.dataset_service, "ensure_member", lambda *_args: None)

    def stop_before_storage(**_kwargs):
        raise StorageBoundaryError

    monkeypatch.setattr(evidence_capsules, "_capsule_path", stop_before_storage)

    def persist(payload: dict):
        return evidence_capsules.persist_evidence_capsule(
            evidence_capsules.EvidenceCapsulePersistRequest(capsule=payload, capsule_id="review-capsule"),
            tenant_id=uuid4(),
            account_id="reader",
            db=object(),
        )

    return persist


@pytest.mark.parametrize("value", [1, True, [1], {"value": "hash"}, None, 0, False])
def test_lax_persistence_still_rejects_invalid_hash_values(value: object, capsule_persistence_boundary) -> None:
    with pytest.raises(HTTPException) as error:
        capsule_persistence_boundary({"schema": "mimirq.evidence_capsule.v1", "capsule_hash": value, "citations": []})
    assert error.value.status_code == 400
    assert "capsule_hash" in error.value.detail


def test_lax_persistence_requires_a_hash(capsule_persistence_boundary) -> None:
    with pytest.raises(HTTPException) as error:
        capsule_persistence_boundary({"schema": "mimirq.evidence_capsule.v1", "citations": []})
    assert error.value.status_code == 400
    assert "capsule_hash" in error.value.detail


def test_lax_persistence_preserves_its_supported_string_hash(capsule_persistence_boundary) -> None:
    with pytest.raises(StorageBoundaryError):
        capsule_persistence_boundary(
            {"schema": "mimirq.evidence_capsule.v1", "capsule_hash": "test-hash", "citations": []}
        )
