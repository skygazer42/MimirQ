from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import document_access_service


@pytest.mark.parametrize("mode", [0, False])
def test_invalid_provided_document_mode_is_not_treated_as_inherited_access(mode):
    document = SimpleNamespace(access_mode=mode, owner_id="other")
    dataset = SimpleNamespace(owner_id=None)
    with pytest.raises(AttributeError):
        document_access_service.assert_document_acl_readable(
            object(), tenant_id=uuid4(), account_id="reader", document=document, dataset=dataset
        )


def test_stored_null_document_mode_keeps_real_inherited_access():
    document_access_service.assert_document_acl_readable(
        object(), tenant_id=uuid4(), account_id="reader",
        document=SimpleNamespace(access_mode=None, owner_id="other"), dataset=SimpleNamespace(owner_id=None),
    )
