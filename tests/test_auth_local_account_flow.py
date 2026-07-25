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
    monkeypatch.setattr(settings, "INITIAL_REGISTRATION_TOKEN", "sha256:fc17cbe42905e3308ba7175fd672651094e30c926f2bdd426636f12dd19df41b", raising=False)

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
