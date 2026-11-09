from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.evidence_capsules import _capsule_envelope, _extract_capsule_binding


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


def test_missing_stored_capsule_binding_stays_missing_for_authorization() -> None:
    tenant, owner, capsule = _extract_capsule_binding({"capsule": {}}, allow_legacy_raw=False)
    assert tenant is None
    assert owner is None
    assert capsule == {}
