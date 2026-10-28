from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.v1.auth as auth_module
from app.core.config import settings
from app.core.database import Base
from app.core.security import hash_password
from app.models.tenant import Tenant, TenantMember
from app.models.user import User
from app.services.user_service import UserService


@pytest.fixture(autouse=True)
def _closed_signup_by_default(monkeypatch):
    monkeypatch.setitem(settings.__dict__, "LOCAL_ACCOUNT_REGISTRATION_ENABLED", False)


def _build_auth_test_client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[User.__table__, Tenant.__table__, TenantMember.__table__])
    test_session = sessionmaker(bind=engine)

    def _get_test_db():
        db = test_session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(auth_module.router, prefix="/auth")
    app.dependency_overrides[auth_module.get_db] = _get_test_db
    return engine, test_session, app


@pytest.fixture
def local_accounts(monkeypatch):
    import app.api.v1.rbac as rbac_module

    monkeypatch.setenv("ENV", "development")
    overrides = {
        "AUTH_MODE": "jwt", "ALGORITHM": "HS256", "SECRET_KEY": "k" * 40,
        "SECRET_KEY_FALLBACKS": "", "JWT_ISSUER": "", "JWT_AUDIENCE": "",
        "JWT_TENANT_CLAIM": "tenant_id", "JWT_ENFORCE_TENANT_HEADER_MATCH": False,
        "JWT_GROUPS_SYNC_ENABLED": False, "JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED": False,
        "DEFAULT_TENANT_ID": str(uuid4()), "INITIAL_REGISTRATION_TOKEN": "bootstrap-secret",
        "LOCAL_ACCOUNT_REGISTRATION_ENABLED": True,
    }
    for key, value in overrides.items():
        monkeypatch.setitem(settings.__dict__, key, value)
    engine, session, application = _build_auth_test_client()
    application.include_router(rbac_module.router, prefix="/rbac")
    try:
        with TestClient(application) as client:
            yield client, session
    finally:
        engine.dispose()


def _bootstrap_owner(client):
    response = client.post(
        "/auth/register", headers={"X-Bootstrap-Token": "bootstrap-secret"},
        json={"email": "owner@example.com", "username": "owner", "password": "valid-owner-password"},
    )
    assert response.status_code == 201, response.text
    return response.json()


_SIGNUP_PAYLOAD = {"email": "reader@example.com", "username": "reader", "password": "valid-reader-password"}


def test_public_auth_policy_tracks_setup_and_signup_without_exposing_secrets(local_accounts, monkeypatch):
    client, _session = local_accounts
    policy = client.get("/auth/policy")
    assert policy.status_code == 200
    assert policy.headers["cache-control"] == "no-store"
    assert policy.json() == {
        "initialized": False, "registration_enabled": False, "bootstrap_enabled": True,
        "bootstrap_token_required": False, "password_min_length": 8,
    }
    _bootstrap_owner(client)
    assert client.get("/auth/policy").json()["registration_enabled"] is True
    assert client.get("/auth/policy").json()["bootstrap_enabled"] is False
    monkeypatch.setitem(settings.__dict__, "LOCAL_ACCOUNT_REGISTRATION_ENABLED", False)
    assert client.get("/auth/policy").json()["registration_enabled"] is False


def test_production_policy_hides_unusable_setup_without_a_bootstrap_token(local_accounts, monkeypatch):
    client, _session = local_accounts
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(settings, "INITIAL_REGISTRATION_TOKEN", "")
    policy = client.get("/auth/policy").json()
    assert policy["bootstrap_enabled"] is False
    assert policy["bootstrap_token_required"] is True


def test_signup_before_workspace_setup_never_creates_owner_or_tenant(local_accounts):
    client, session = local_accounts
    denied = client.post("/auth/signup", json=_SIGNUP_PAYLOAD)
    assert denied.status_code == 409
    with session() as db:
        assert db.query(User).count() == 0
        assert db.query(TenantMember).count() == 0
        assert db.query(Tenant).count() == 0


def test_disabled_signup_rejects_stale_browser_policy_without_creating_user(local_accounts, monkeypatch):
    client, session = local_accounts
    _bootstrap_owner(client)
    monkeypatch.setitem(settings.__dict__, "LOCAL_ACCOUNT_REGISTRATION_ENABLED", False)
    denied = client.post("/auth/signup", json=_SIGNUP_PAYLOAD)
    assert denied.status_code == 403
    with session() as db:
        assert db.query(User).count() == 1
        assert db.query(TenantMember).count() == 1


def test_signup_gets_viewer_and_only_admin_can_promote_with_immediate_effect(local_accounts):
    client, session = local_accounts
    owner = _bootstrap_owner(client)
    created = client.post("/auth/signup", json=_SIGNUP_PAYLOAD)
    assert created.status_code == 201, created.text
    reader = created.json()
    headers = {"Authorization": f"Bearer {reader['token']['access_token']}"}
    owner_headers = {"Authorization": f"Bearer {owner['token']['access_token']}"}
    access = client.get("/rbac/me", headers=headers)
    assert access.status_code == 200, access.text
    assert access.json()["role"] == "viewer"
    assert "settings.write" not in access.json()["permissions"]
    assert client.get("/rbac/members", headers=headers).status_code == 403
    path = f"/rbac/members/{reader['user']['id']}"
    assert client.patch(path, headers=headers, json={"role": "admin"}).status_code == 403
    promoted = client.patch(path, headers=owner_headers, json={"role": "editor"})
    assert promoted.status_code == 200, promoted.text
    assert client.get("/rbac/me", headers=headers).json()["role"] == "editor"
    promoted = client.patch(path, headers=owner_headers, json={"role": "admin"})
    assert promoted.status_code == 200
    assert "settings.write" in client.get("/rbac/me", headers=headers).json()["permissions"]
    with session() as db:
        assert db.query(User).count() == 2
        assert db.query(TenantMember).filter(TenantMember.user_id == reader["user"]["id"]).one().role == "admin"


def test_signup_rejects_caller_controlled_role(local_accounts):
    client, session = local_accounts
    _bootstrap_owner(client)
    denied = client.post("/auth/signup", json={**_SIGNUP_PAYLOAD, "role": "owner"})
    assert denied.status_code == 422
    with session() as db:
        assert db.query(User).count() == 1


def test_production_signup_does_not_reuse_bootstrap_or_require_its_token(local_accounts, monkeypatch):
    client, session = local_accounts
    monkeypatch.setenv("ENV", "production")
    _bootstrap_owner(client)
    created = client.post("/auth/signup", json=_SIGNUP_PAYLOAD)
    assert created.status_code == 201, created.text
    assert client.post("/auth/register", json={
        "email": "intruder@example.com", "username": "intruder", "password": "another-valid-password",
    }).status_code == 409
    with session() as db:
        assert db.query(TenantMember).filter(TenantMember.role == "owner").count() == 1
        assert db.query(TenantMember).filter(TenantMember.role == "viewer").count() == 1


def test_signup_refuses_inactive_tenant_without_orphaned_account(local_accounts):
    client, session = local_accounts
    _bootstrap_owner(client)
    with session() as db:
        db.query(Tenant).one().status = "suspended"
        db.commit()
    assert client.get("/auth/policy").json()["registration_enabled"] is False
    denied = client.post("/auth/signup", json=_SIGNUP_PAYLOAD)
    assert denied.status_code == 403
    with session() as db:
        assert db.query(User).count() == 1


def test_duplicate_signup_rolls_back_and_next_signup_still_works(local_accounts):
    client, session = local_accounts
    _bootstrap_owner(client)
    assert client.post("/auth/signup", json=_SIGNUP_PAYLOAD).status_code == 201
    assert client.post("/auth/signup", json={**_SIGNUP_PAYLOAD, "username": "different"}).status_code == 400
    assert client.post("/auth/signup", json={**_SIGNUP_PAYLOAD, "email": "different@example.com"}).status_code == 400
    assert client.post("/auth/signup", json={
        **_SIGNUP_PAYLOAD, "username": "another", "email": "another@example.com",
    }).status_code == 201
    with session() as db:
        assert db.query(User).count() == 3
        assert db.query(TenantMember).count() == 3


def test_admin_member_listing_identifies_local_users_and_preserves_external_members(local_accounts):
    client, session = local_accounts
    owner = _bootstrap_owner(client)
    created = client.post("/auth/signup", json=_SIGNUP_PAYLOAD)
    assert created.status_code == 201
    reader_id = created.json()["user"]["id"]
    with session() as db:
        db.add(TenantMember(
            tenant_id=db.query(Tenant).one().id, user_id="external|user-42", role="viewer", is_active=True,
        ))
        db.commit()
    headers = {"Authorization": f"Bearer {owner['token']['access_token']}"}
    response = client.get("/rbac/members", headers=headers)
    assert response.status_code == 200, response.text
    members = {member["user_id"]: member for member in response.json()["items"]}
    assert members[reader_id]["username"] == "reader"
    assert members[reader_id]["email"] == "reader@example.com"
    assert members["external|user-42"]["username"] is None
    assert members["external|user-42"]["email"] is None
    assert "password_hash" not in response.text
    updated = client.patch(f"/rbac/members/{reader_id}", headers=headers, json={"role": "editor"})
    assert updated.json()["username"] == "reader"
    assert updated.json()["email"] == "reader@example.com"
    assert client.get("/rbac/members?limit=1", headers=headers).json()["total"] == 3


def test_signup_does_not_weaken_last_admin_protection(local_accounts):
    client, _session = local_accounts
    owner = _bootstrap_owner(client)
    assert client.post("/auth/signup", json=_SIGNUP_PAYLOAD).status_code == 201
    headers = {"Authorization": f"Bearer {owner['token']['access_token']}"}
    denied = client.patch(f"/rbac/members/{owner['user']['id']}", headers=headers, json={"role": "viewer"})
    assert denied.status_code == 409
    assert client.get("/rbac/me", headers=headers).json()["role"] == "owner"


def test_signup_integrity_conflict_rolls_back_account_and_membership(local_accounts):
    from sqlalchemy import event
    from sqlalchemy.exc import IntegrityError

    client, session = local_accounts
    _bootstrap_owner(client)

    def _simulate_concurrent_conflict(db, _context, _instances):
        if any(isinstance(value, TenantMember) for value in db.new):
            raise IntegrityError("member insert", {}, Exception("simulated competing insert"))

    event.listen(session.class_, "before_flush", _simulate_concurrent_conflict)
    try:
        denied = client.post("/auth/signup", json=_SIGNUP_PAYLOAD)
        assert denied.status_code == 409, denied.text
        assert "competing insert" not in denied.text
    finally:
        event.remove(session.class_, "before_flush", _simulate_concurrent_conflict)
    with session() as db:
        assert db.query(User).count() == 1
        assert db.query(TenantMember).count() == 1
    assert client.post("/auth/signup", json=_SIGNUP_PAYLOAD).status_code == 201


def test_local_account_bootstrap_login_and_me(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY", "k" * 40, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False, raising=False)
    monkeypatch.setattr(settings, "JWT_GROUPS_SYNC_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DEFAULT_TENANT_ID", str(uuid4()), raising=False)
    monkeypatch.setattr(settings, "INITIAL_REGISTRATION_TOKEN", "", raising=False)

    engine, test_session, app = _build_auth_test_client()

    try:
        with TestClient(app) as client:
            registered = client.post(
                "/auth/register",
                json={
                    "email": "Owner@Example.com",
                    "username": "owner",
                    "password": "correct-horse-battery-staple",
                },
            )
            assert registered.status_code == 201, registered.text
            registration = registered.json()
            assert registration["user"]["email"] == "owner@example.com"
            assert registration["token"]["token_type"] == "bearer"

            token = registration["token"]["access_token"]
            current_user = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert current_user.status_code == 200, current_user.text
            assert current_user.json()["id"] == registration["user"]["id"]

            invalid_login = client.post(
                "/auth/login",
                json={"identifier": "OWNER@EXAMPLE.COM", "password": "wrong-password"},
            )
            assert invalid_login.status_code == 401

            logged_in = client.post(
                "/auth/login",
                json={
                    "identifier": "OWNER@EXAMPLE.COM",
                    "password": "correct-horse-battery-staple",
                },
            )
            assert logged_in.status_code == 200, logged_in.text
            assert logged_in.json()["user"]["last_login_at"] is not None

            later_registration = client.post(
                "/auth/register",
                json={
                    "email": "later@example.com",
                    "username": "later",
                    "password": "another-valid-password",
                },
            )
            assert later_registration.status_code == 409
            assert later_registration.json()["detail"] == "Initial registration is closed; contact an administrator"

        with test_session() as db:
            assert db.query(User).count() == 1
            assert db.query(TenantMember).count() == 1
    finally:
        engine.dispose()


def test_production_bootstrap_registration_requires_token(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY", "k" * 40, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False, raising=False)
    monkeypatch.setattr(settings, "JWT_GROUPS_SYNC_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DEFAULT_TENANT_ID", str(uuid4()), raising=False)
    monkeypatch.setattr(settings, "INITIAL_REGISTRATION_TOKEN", "bootstrap-secret", raising=False)

    engine, _test_session, app = _build_auth_test_client()

    try:
        with TestClient(app) as client:
            denied = client.post(
                "/auth/register",
                json={
                    "email": "owner@example.com",
                    "username": "owner",
                    "password": "correct-horse-battery-staple",
                },
            )
            assert denied.status_code == 403
            assert denied.json()["detail"] == "Initial registration bootstrap token required"
    finally:
        engine.dispose()


def test_production_bootstrap_registration_accepts_matching_token(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY", "k" * 40, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False, raising=False)
    monkeypatch.setattr(settings, "JWT_GROUPS_SYNC_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DEFAULT_TENANT_ID", str(uuid4()), raising=False)
    monkeypatch.setattr(
        settings,
        "INITIAL_REGISTRATION_TOKEN",
        "sha256:fc17cbe42905e3308ba7175fd672651094e30c926f2bdd426636f12dd19df41b",
        raising=False,
    )

    engine, test_session, app = _build_auth_test_client()

    try:
        with TestClient(app) as client:
            registered = client.post(
                "/auth/register",
                headers={"X-Bootstrap-Token": "bootstrap-secret"},
                json={
                    "email": "owner@example.com",
                    "username": "owner",
                    "password": "correct-horse-battery-staple",
                },
            )
            assert registered.status_code == 201, registered.text

        with test_session() as db:
            assert db.query(User).count() == 1
            assert db.query(TenantMember).count() == 1
    finally:
        engine.dispose()


def test_production_existing_owner_registration_still_returns_conflict_without_token(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY", "k" * 40, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False, raising=False)
    monkeypatch.setattr(settings, "JWT_GROUPS_SYNC_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DEFAULT_TENANT_ID", str(uuid4()), raising=False)
    monkeypatch.setattr(settings, "INITIAL_REGISTRATION_TOKEN", "", raising=False)

    engine, _test_session, app = _build_auth_test_client()

    try:
        with TestClient(app) as client:
            first = client.post(
                "/auth/register",
                headers={"X-Bootstrap-Token": "bootstrap-secret"},
                json={
                    "email": "owner@example.com",
                    "username": "owner",
                    "password": "correct-horse-battery-staple",
                },
            )
            assert first.status_code == 403

        monkeypatch.setattr(settings, "INITIAL_REGISTRATION_TOKEN", "bootstrap-secret", raising=False)

        with TestClient(app) as client:
            first = client.post(
                "/auth/register",
                headers={"X-Bootstrap-Token": "bootstrap-secret"},
                json={
                    "email": "owner@example.com",
                    "username": "owner",
                    "password": "correct-horse-battery-staple",
                },
            )
            assert first.status_code == 201, first.text

            second = client.post(
                "/auth/register",
                json={
                    "email": "later@example.com",
                    "username": "later",
                    "password": "another-valid-password",
                },
            )
            assert second.status_code == 409
            assert second.json()["detail"] == "Initial registration is closed; contact an administrator"
    finally:
        engine.dispose()


def test_get_current_tenant_id_ignores_inactive_memberships_and_tenants() -> None:
    engine, test_session, _app = _build_auth_test_client()

    try:
        with test_session() as db:
            user = User(
                email="owner@example.com",
                username="owner",
                password_hash=hash_password("correct-horse-battery-staple"),
                is_active=True,
            )
            db.add(user)
            db.flush()

            active_current_tenant = Tenant(name="active-current", status="active", plan="basic")
            active_fallback_tenant = Tenant(name="active-fallback", status="active", plan="basic")
            inactive_member_tenant = Tenant(name="inactive-member-tenant", status="active", plan="basic")
            inactive_tenant = Tenant(name="inactive-tenant", status="inactive", plan="basic")
            db.add_all([active_current_tenant, active_fallback_tenant, inactive_member_tenant, inactive_tenant])
            db.flush()

            now = datetime.now(timezone.utc)
            db.add_all(
                [
                    TenantMember(
                        tenant_id=active_current_tenant.id,
                        user_id=str(user.id),
                        role="owner",
                        is_active=True,
                        is_current=True,
                        created_at=now - timedelta(hours=4),
                        updated_at=now - timedelta(hours=4),
                    ),
                    TenantMember(
                        tenant_id=active_fallback_tenant.id,
                        user_id=str(user.id),
                        role="owner",
                        is_active=True,
                        is_current=False,
                        created_at=now - timedelta(hours=3),
                        updated_at=now - timedelta(hours=3),
                    ),
                    TenantMember(
                        tenant_id=inactive_member_tenant.id,
                        user_id=str(user.id),
                        role="owner",
                        is_active=False,
                        is_current=True,
                        created_at=now - timedelta(hours=2),
                        updated_at=now - timedelta(hours=2),
                    ),
                    TenantMember(
                        tenant_id=inactive_tenant.id,
                        user_id=str(user.id),
                        role="owner",
                        is_active=True,
                        is_current=True,
                        created_at=now - timedelta(hours=1),
                        updated_at=now - timedelta(hours=1),
                    ),
                ]
            )
            db.commit()

            assert UserService.get_current_tenant_id(db, user_id=str(user.id)) == active_current_tenant.id

            current_member = (
                db.query(TenantMember)
                .filter(
                    TenantMember.user_id == str(user.id),
                    TenantMember.tenant_id == active_current_tenant.id,
                )
                .one()
            )
            current_member.is_active = False
            current_member.is_current = False
            db.commit()

            assert UserService.get_current_tenant_id(db, user_id=str(user.id)) == active_fallback_tenant.id

            fallback_member = (
                db.query(TenantMember)
                .filter(
                    TenantMember.user_id == str(user.id),
                    TenantMember.tenant_id == active_fallback_tenant.id,
                    TenantMember.is_active.is_(True),
                )
                .one()
            )
            fallback_member.is_active = False
            db.commit()

            assert UserService.get_current_tenant_id(db, user_id=str(user.id)) is None
    finally:
        engine.dispose()


def test_authenticate_rejects_ambiguous_identifier_collision() -> None:
    engine, test_session, _app = _build_auth_test_client()

    try:
        with test_session() as db:
            db.add_all(
                [
                    User(
                        email="owner@example.com",
                        username="owner",
                        password_hash=hash_password("owner-password"),
                        is_active=True,
                    ),
                    User(
                        email="other@example.com",
                        username="owner@example.com",
                        password_hash=hash_password("other-password"),
                        is_active=True,
                    ),
                ]
            )
            db.commit()

            for password in ("owner-password", "other-password"):
                with pytest.raises(HTTPException) as excinfo:
                    UserService.authenticate(db, "owner@example.com", password)

                assert excinfo.value.status_code == 401
                assert excinfo.value.detail == "Invalid credentials"
    finally:
        engine.dispose()


def test_create_user_rejects_cross_field_namespace_collisions_case_insensitively() -> None:
    engine, test_session, _app = _build_auth_test_client()

    try:
        with test_session() as db:
            db.add(
                User(
                    email="owner@example.com",
                    username="Owner",
                    password_hash=hash_password("correct-horse-battery-staple"),
                    is_active=True,
                )
            )
            db.commit()

            with pytest.raises(HTTPException) as username_exc:
                UserService.create_user(
                    db,
                    email="other@example.com",
                    username="OWNER@example.com",
                    password="another-valid-password",
                )
            assert username_exc.value.status_code == 400

            with pytest.raises(HTTPException) as email_exc:
                UserService.create_user(
                    db,
                    email="owner",
                    username="later",
                    password="another-valid-password",
                )
            assert email_exc.value.status_code == 400
    finally:
        engine.dispose()
