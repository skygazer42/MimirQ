import uuid

import pytest

from app.core.config import settings
from app.rag.kg.models import _default_tenant


def test_default_tenant_returns_uuid(monkeypatch: pytest.MonkeyPatch):
    tid = uuid.uuid4()
    monkeypatch.setattr(settings, "DEFAULT_TENANT_ID", str(tid))
    assert _default_tenant() == tid
    assert isinstance(_default_tenant(), uuid.UUID)


def test_default_tenant_invalid_falls_back_to_zero(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "DEFAULT_TENANT_ID", "not-a-uuid")
    assert _default_tenant() == uuid.UUID("00000000-0000-0000-0000-000000000000")

