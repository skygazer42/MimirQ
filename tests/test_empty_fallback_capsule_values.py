from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.evaluation import evidence_capsules
from app.api.v1.evaluation.evidence_capsules import _capsule_envelope


@pytest.mark.parametrize("field", ["tenant_id", "owner_account_id"])
@pytest.mark.parametrize("value", ["", 0, False])
def test_supplied_capsule_binding_cannot_be_treated_as_unasserted(field, value) -> None:
    with pytest.raises(HTTPException) as error:
        _capsule_envelope(capsule={field: value}, tenant_id=uuid4(), capsule_id="capsule", account_id="reader")
    assert error.value.status_code == 400


def test_a_new_capsule_can_bind_genuinely_absent_identity() -> None:
    tenant = uuid4()
    result = _capsule_envelope(capsule={}, tenant_id=tenant, capsule_id="capsule", account_id="reader")
    assert result["tenant_id"] == str(tenant)
    assert result["owner_account_id"] == "reader"


def test_missing_stored_capsule_binding_cannot_authorize_a_reader(monkeypatch) -> None:
    monkeypatch.setattr(evidence_capsules, "_read_capsule_payload", lambda _path: {"capsule": {}})
    with pytest.raises(HTTPException) as error:
        evidence_capsules._load_authorized_capsule(
            Path("not-read.json"), tenant_id=uuid4(), account_id="reader", allow_legacy_raw=False
        )
    assert error.value.status_code == 404
