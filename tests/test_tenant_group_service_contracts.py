import json
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from starlette.datastructures import State

from app.api.v1 import scim
from app.core.database import Base
from app.core.exceptions import BadRequestError, ConflictError, MimirQError
from app.core.request_state import bind_request_state, reset_request_state
from app.models.tenant import Tenant, TenantMember
from app.models.tenant_group import TenantGroup, TenantGroupMember
from app.services import tenant_group_service


@pytest.fixture
def group_db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine, tables=[Tenant.__table__, TenantMember.__table__, TenantGroup.__table__, TenantGroupMember.__table__]
    )
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_group_validation_raises_a_business_error(group_db: Session) -> None:
    with pytest.raises(BadRequestError, match="name is required"):
        tenant_group_service.create_group(group_db, tenant_id=uuid4(), name="   ")


def test_group_conflict_raises_a_business_error(group_db: Session) -> None:
    tenant_id = uuid4()
    tenant_group_service.create_group(group_db, tenant_id=tenant_id, name="readers")
    with pytest.raises(ConflictError, match="Group name already exists"):
        tenant_group_service.create_group(group_db, tenant_id=tenant_id, name="readers")


def test_group_lookup_retains_not_found_contract(group_db: Session) -> None:
    with pytest.raises(MimirQError) as error:
        tenant_group_service.get_group(group_db, tenant_id=uuid4(), group_id=uuid4())
    assert error.value.status_code == 404
    assert error.value.error_code == "NOT_FOUND"
    assert error.value.message == "Group not found"


def test_group_membership_rejects_accounts_outside_the_tenant(group_db: Session) -> None:
    tenant_id = uuid4()
    other_tenant = uuid4()
    group_db.add(Tenant(id=other_tenant, name="other"))
    group_db.add(TenantMember(tenant_id=other_tenant, user_id="outside", role="viewer"))
    group_db.commit()
    group = tenant_group_service.create_group(group_db, tenant_id=tenant_id, name="readers")
    with pytest.raises(BadRequestError, match="Unknown tenant members: outside"):
        tenant_group_service.add_members(group_db, tenant_id=tenant_id, group_id=group.id, member_ids=["outside"])
    assert group_db.query(TenantGroupMember).count() == 0


def test_group_cache_reuses_the_lookup_and_keeps_tenant_scope(group_db: Session) -> None:
    tenant_id = uuid4()
    group = tenant_group_service.create_group(group_db, tenant_id=tenant_id, name="readers")
    group_id = group.id
    group_db.add(TenantGroupMember(tenant_id=tenant_id, group_id=group_id, user_id="reader"))
    group_db.commit()
    lookups: list[str] = []

    def record_lookup(
        _connection: object, _cursor: object, statement: str, _parameters: object, _context: object, _many: bool
    ) -> None:
        lookups.append(statement)

    event.listen(group_db.get_bind(), "before_cursor_execute", record_lookup)
    token = bind_request_state(State())
    try:
        assert tenant_group_service.resolve_account_group_ids(group_db, tenant_id=tenant_id, account_id="reader") == {
            group_id
        }
        assert tenant_group_service.resolve_account_group_ids(group_db, tenant_id=tenant_id, account_id="reader") == {
            group_id
        }
        assert len(lookups) == 1
        assert tenant_group_service.resolve_account_group_ids(group_db, tenant_id=uuid4(), account_id="reader") == set()
        assert len(lookups) == 2
    finally:
        reset_request_state(token)
        event.remove(group_db.get_bind(), "before_cursor_execute", record_lookup)


def test_invalid_internal_group_cache_remains_visible(group_db: Session) -> None:
    state = State()
    state._mimirq_group_ids_cache = []
    token = bind_request_state(state)
    try:
        with pytest.raises(AttributeError):
            tenant_group_service.resolve_account_group_ids(group_db, tenant_id=uuid4(), account_id="reader")
    finally:
        reset_request_state(token)


def test_scim_group_not_found_keeps_its_protocol_response(group_db: Session) -> None:
    response = scim.get_group(uuid4(), tenant_id=uuid4(), _actor="scim", db=group_db)
    assert response.status_code == 404
    assert response.media_type == "application/scim+json"
    assert json.loads(response.body) == {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
        "status": "404",
        "detail": "Group not found",
    }
