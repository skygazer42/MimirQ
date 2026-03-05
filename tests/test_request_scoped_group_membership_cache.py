from __future__ import annotations

import importlib
from types import SimpleNamespace
from uuid import uuid4

import pytest


class _FakeQuery:
    def __init__(self, *, rows):  # noqa: ANN001
        self._rows = list(rows)

    def filter(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def all(self):  # noqa: ANN201
        return list(self._rows)


class _FakeSession:
    def __init__(self, *, rows):  # noqa: ANN001
        self._rows = list(rows)
        self.query_calls = 0

    def query(self, *args, **_kwargs):  # noqa: ANN001
        self.query_calls += 1
        return _FakeQuery(rows=self._rows)


def _import_or_fail(module: str):  # noqa: ANN001
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError:
        pytest.fail(f"Expected module to exist: {module}")


def test_resolve_account_group_ids_is_cached_in_request_state():  # noqa: ANN001
    """
    Wave25-T15: group membership lookups should be request-scoped cached.

    Caching is keyed on request.state so repeated permission checks in one request
    don't issue repeated DB queries.
    """
    rs = _import_or_fail("app.core.request_state")
    tgs = _import_or_fail("app.services.tenant_group_service")

    if not hasattr(tgs.TenantGroupService, "resolve_account_group_ids"):
        pytest.fail("Expected TenantGroupService.resolve_account_group_ids to exist")

    tenant_id = uuid4()
    group_id = uuid4()
    db = _FakeSession(rows=[(group_id,)])

    state = SimpleNamespace()
    token = rs.bind_request_state(state)
    try:
        ids1 = tgs.TenantGroupService.resolve_account_group_ids(db, tenant_id=tenant_id, account_id="bob")
        ids2 = tgs.TenantGroupService.resolve_account_group_ids(db, tenant_id=tenant_id, account_id="bob")
    finally:
        rs.reset_request_state(token)

    assert isinstance(ids1, set)
    assert ids1 == {group_id}
    assert ids2 == {group_id}
    assert db.query_calls == 1


def test_resolve_account_group_ids_falls_back_when_no_request_state():  # noqa: ANN001
    rs = _import_or_fail("app.core.request_state")
    tgs = _import_or_fail("app.services.tenant_group_service")

    if not hasattr(tgs.TenantGroupService, "resolve_account_group_ids"):
        pytest.fail("Expected TenantGroupService.resolve_account_group_ids to exist")

    # Ensure no request state is bound.
    token = rs.bind_request_state(None)
    rs.reset_request_state(token)

    tenant_id = uuid4()
    group_id = uuid4()
    db = _FakeSession(rows=[(group_id,)])
    ids = tgs.TenantGroupService.resolve_account_group_ids(db, tenant_id=tenant_id, account_id="bob")
    assert isinstance(ids, set)
    assert ids == {group_id}
    assert db.query_calls == 1
