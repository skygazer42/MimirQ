import pytest

from app.rag.core.evidence_capsule_builder import validate_evidence_capsule


@pytest.mark.parametrize("value", [1, True, ["hash"], {"value": "hash"}, 0, False])
def test_basic_capsule_validation_rejects_non_string_hashes_when_strict_checks_are_off(value):
    payload = {"schema": "mimirq.evidence_capsule.v1", "capsule_hash": value, "citations": []}
    assert validate_evidence_capsule(payload, strict=False, verify_signature=False) == (False, "invalid_capsule_hash")


@pytest.mark.parametrize("payload", [{}, {"capsule_hash": None}, {"capsule_hash": ""}, {"capsule_hash": "  "}])
def test_basic_capsule_validation_keeps_the_missing_hash_error(payload):
    capsule = {"schema": "mimirq.evidence_capsule.v1", "citations": [], **payload}
    assert validate_evidence_capsule(capsule, strict=False, verify_signature=False) == (False, "missing_capsule_hash")


def test_basic_capsule_validation_preserves_lax_string_hash_support():
    payload = {"schema": "mimirq.evidence_capsule.v1", "capsule_hash": " external-hash ", "citations": []}
    assert validate_evidence_capsule(payload, strict=False, verify_signature=False) == (True, "ok")
