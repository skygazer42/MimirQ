from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.v1.auth as auth_module
from app.core.config import settings
from app.core.database import Base
from app.core.exceptions import MimirQError, register_exception_handlers
from app.core.security import hash_password
from app.models.tenant import Tenant, TenantMember
from app.models.user import User
from app.services.user_service import (
    authenticate_user,
    create_user,
    get_current_tenant_id,
)


@pytest.mark.parametrize(
    ("active", "password", "status_code", "error_code"),
    [
        (True, "wrong-password", 401, "AUTHENTICATION_ERROR"),
        (False, "correct-horse-battery-staple", 403, "AUTHORIZATION_ERROR"),
    ],
)
def test_authentication_failures_use_application_errors(
    active: bool, password: str, status_code: int, error_code: str
) -> None:
    engine, test_session, _app = _build_auth_test_client()
    try:
        with test_session() as db:
            db.add(
                User(
                    email="owner@example.com",
                    username="owner",
                    password_hash=hash_password("correct-horse-battery-staple"),
                    is_active=active,
                )
            )
            db.commit()
            with pytest.raises(MimirQError) as failure:
                authenticate_user(db, "owner", password)
            assert failure.value.status_code == status_code
            assert failure.value.error_code == error_code
    finally:
        engine.dispose()


def test_registration_configuration_failure_hides_internal_detail_and_rolls_back(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setattr(settings, "DEFAULT_TENANT_ID", "invalid-tenant")
    engine, test_session, app = _build_auth_test_client()
    register_exception_handlers(app)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/auth/register",
                json={"email": "owner@example.com", "username": "owner", "password": "valid-password"},
                headers={"X-Request-ID": "registration-config-error"},
            )
        assert response.status_code == 500
        assert response.json() == {
            "error": "INTERNAL_ERROR",
            "message": "An unexpected error occurred. Please try again later.",
            "request_id": "registration-config-error",
        }
        with test_session() as db:
            assert db.query(User).count() == 0
            assert db.query(TenantMember).count() == 0
    finally:
        engine.dispose()


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
    register_exception_handlers(app)
    app.include_router(auth_module.router, prefix="/auth")
    app.dependency_overrides[auth_module.get_db] = _get_test_db
    return engine, test_session, app


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
            assert invalid_login.json() == {"error": "AUTHENTICATION_ERROR", "message": "Invalid credentials"}

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
            assert later_registration.json()["error"] == "CONFLICT"
            assert later_registration.json()["message"] == "Initial registration is closed; contact an administrator"

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
            assert denied.json()["message"] == "Initial registration bootstrap token required"
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
            assert second.json()["message"] == "Initial registration is closed; contact an administrator"
    finally:
        engine.dispose()


@pytest.mark.parametrize("fallback_current", [False, None])
def test_get_current_tenant_id_ignores_inactive_memberships_and_tenants(fallback_current: bool | None) -> None:
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

            fallback_member = db.query(TenantMember).filter(TenantMember.tenant_id == active_fallback_tenant.id).one()
            # Update after insertion so the legacy NULL is not replaced by the model's insert default.
            fallback_member.is_current = fallback_current
            db.commit()
            assert get_current_tenant_id(db, user_id=str(user.id)) == active_current_tenant.id

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

            assert get_current_tenant_id(db, user_id=str(user.id)) == active_fallback_tenant.id

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

            assert get_current_tenant_id(db, user_id=str(user.id)) is None
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
                with pytest.raises(MimirQError) as excinfo:
                    authenticate_user(db, "owner@example.com", password)

                assert excinfo.value.status_code == 401
                assert excinfo.value.message == "Invalid credentials"
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

            with pytest.raises(MimirQError) as username_exc:
                create_user(
                    db,
                    email="other@example.com",
                    username="OWNER@example.com",
                    password="another-valid-password",
                    password_min_length=settings.PASSWORD_MIN_LENGTH,
                    default_tenant_id=settings.DEFAULT_TENANT_ID,
                )
            assert username_exc.value.status_code == 400

            with pytest.raises(MimirQError) as email_exc:
                create_user(
                    db,
                    email="owner",
                    username="later",
                    password="another-valid-password",
                    password_min_length=settings.PASSWORD_MIN_LENGTH,
                    default_tenant_id=settings.DEFAULT_TENANT_ID,
                )
            assert email_exc.value.status_code == 400
    finally:
        engine.dispose()


def test_registration_password_policy_keeps_bad_request_response(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setattr(settings, "PASSWORD_MIN_LENGTH", 12)
    engine, test_session, app = _build_auth_test_client()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/auth/register",
                json={"email": "owner@example.com", "username": "owner", "password": "12345678"},
            )
        assert response.status_code == 400
        assert response.json() == {"error": "BAD_REQUEST", "message": "Password must be at least 12 characters"}
        with test_session() as db:
            assert db.query(User).count() == 0
    finally:
        engine.dispose()


def test_current_user_malformed_account_id_keeps_not_found_response() -> None:
    engine, _test_session, app = _build_auth_test_client()
    app.dependency_overrides[auth_module.get_current_account_id] = lambda: "not-a-uuid"
    try:
        with TestClient(app) as client:
            response = client.get("/auth/me")
        assert response.status_code == 404
        assert response.json() == {"error": "NOT_FOUND", "message": "User not found"}
    finally:
        engine.dispose()
