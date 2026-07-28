from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, settings
from app.core.database import Base
from app.core.security import verify_password
from app.models.tenant import Tenant, TenantMember
from app.models.user import User


def _set_prod_bootstrap_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("ALLOWED_HOSTS", "mimirq.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("JWT_TENANT_CLAIM", "tenant_id")
    monkeypatch.setenv("DB_CREATE_ALL_ON_STARTUP", "false")
    monkeypatch.setenv("MIMIRQ_DB_CREATE_ALL_ON_STARTUP", "false")
    monkeypatch.setenv("DB_RUNTIME_MIGRATIONS_ENABLED", "false")
    monkeypatch.setenv("MIMIRQ_DB_RUNTIME_MIGRATIONS_ENABLED", "false")


def _build_test_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[User.__table__, Tenant.__table__, TenantMember.__table__])
    return engine, sessionmaker(bind=engine)


def test_initial_admin_bootstrap_is_disabled_when_env_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_prod_bootstrap_env(monkeypatch)
    monkeypatch.delenv("INITIAL_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("INITIAL_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD_FILE", raising=False)

    configured = Settings()

    assert configured.INITIAL_ADMIN_EMAIL == ""
    assert configured.INITIAL_ADMIN_USERNAME == ""
    assert configured.INITIAL_ADMIN_PASSWORD == ""
    assert configured.INITIAL_ADMIN_PASSWORD_FILE == ""


def test_initial_admin_bootstrap_requires_complete_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_prod_bootstrap_env(monkeypatch)
    monkeypatch.setenv("INITIAL_ADMIN_EMAIL", "owner@example.com")
    monkeypatch.delenv("INITIAL_ADMIN_USERNAME", raising=False)
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "correct-horse-battery-staple")
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD_FILE", raising=False)

    with pytest.raises(ValueError) as excinfo:
        Settings()

    assert "INITIAL_ADMIN_EMAIL, INITIAL_ADMIN_USERNAME" in str(excinfo.value)


def test_initial_admin_bootstrap_rejects_password_and_password_file_together(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_prod_bootstrap_env(monkeypatch)
    monkeypatch.setenv("INITIAL_ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("INITIAL_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "correct-horse-battery-staple")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD_FILE", "/tmp/owner-password.txt")

    with pytest.raises(ValueError) as excinfo:
        Settings()

    assert "INITIAL_ADMIN_PASSWORD and INITIAL_ADMIN_PASSWORD_FILE are mutually exclusive" in str(excinfo.value)


def test_initial_admin_bootstrap_rejects_invalid_email(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_prod_bootstrap_env(monkeypatch)
    monkeypatch.setenv("INITIAL_ADMIN_EMAIL", "not-an-email")
    monkeypatch.setenv("INITIAL_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "correct-horse-battery-staple")
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD_FILE", raising=False)

    with pytest.raises(ValueError) as excinfo:
        Settings()

    assert "INITIAL_ADMIN_EMAIL must be a valid email address" in str(excinfo.value)


def test_initial_admin_validation_never_echoes_password(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_prod_bootstrap_env(monkeypatch)
    password = "leak-me"
    monkeypatch.setenv("INITIAL_ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("INITIAL_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", password)
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD_FILE", raising=False)

    with pytest.raises(ValueError) as excinfo:
        Settings()

    assert "INITIAL_ADMIN_PASSWORD must be at least" in str(excinfo.value)
    assert password not in str(excinfo.value)


def test_initial_admin_bootstrap_creates_owner_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.initial_admin_service import bootstrap_initial_admin_if_configured

    tenant_id = str(uuid4())
    monkeypatch.setattr(settings, "DEFAULT_TENANT_ID", tenant_id, raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_EMAIL", "owner@example.com", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_USERNAME", "owner", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", "correct-horse-battery-staple", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD_FILE", "", raising=False)

    engine, test_session = _build_test_session()
    try:
        with test_session() as db:
            created = bootstrap_initial_admin_if_configured(db)
            assert created is True

            user = db.query(User).filter(User.email == "owner@example.com").one()
            member = db.query(TenantMember).filter(TenantMember.user_id == str(user.id)).one()

            assert user.username == "owner"
            assert verify_password("correct-horse-battery-staple", user.password_hash) is True
            assert str(member.tenant_id) == tenant_id
            assert member.role == "owner"
            assert member.is_active is True
    finally:
        engine.dispose()


def test_initial_admin_bootstrap_is_idempotent_and_keeps_existing_password_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.initial_admin_service import bootstrap_initial_admin_if_configured

    tenant_id = str(uuid4())
    monkeypatch.setattr(settings, "DEFAULT_TENANT_ID", tenant_id, raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_EMAIL", "owner@example.com", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_USERNAME", "owner", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", "correct-horse-battery-staple", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD_FILE", "", raising=False)

    engine, test_session = _build_test_session()
    try:
        with test_session() as db:
            assert bootstrap_initial_admin_if_configured(db) is True
            original_hash = db.query(User).filter(User.email == "owner@example.com").one().password_hash

        monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", "a-different-password", raising=False)

        with test_session() as db:
            assert bootstrap_initial_admin_if_configured(db) is False
            user = db.query(User).filter(User.email == "owner@example.com").one()

            assert user.password_hash == original_hash
            assert verify_password("correct-horse-battery-staple", user.password_hash) is True
            assert db.query(User).count() == 1
            assert db.query(TenantMember).count() == 1
    finally:
        engine.dispose()


def test_initial_admin_bootstrap_rejects_existing_different_member(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.security import hash_password
    from app.services.initial_admin_service import bootstrap_initial_admin_if_configured

    tenant_id = str(uuid4())
    monkeypatch.setattr(settings, "DEFAULT_TENANT_ID", tenant_id, raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_EMAIL", "owner@example.com", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_USERNAME", "owner", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", "correct-horse-battery-staple", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD_FILE", "", raising=False)

    engine, test_session = _build_test_session()
    try:
        with test_session() as db:
            user = User(
                email="existing@example.com",
                username="existing",
                password_hash=hash_password("another-valid-password"),
                is_active=True,
            )
            tenant_uuid = UUID(tenant_id)
            tenant = Tenant(id=tenant_uuid, name=f"tenant-{tenant_id}", status="active", plan="basic")
            db.add_all([user, tenant])
            db.flush()
            db.add(
                TenantMember(
                    tenant_id=tenant_uuid,
                    user_id=str(user.id),
                    role="owner",
                    is_active=True,
                    is_current=True,
                )
            )
            db.commit()

        with test_session() as db:
            with pytest.raises(RuntimeError) as excinfo:
                bootstrap_initial_admin_if_configured(db)

            assert "INITIAL_ADMIN_*" in str(excinfo.value)
            assert db.query(User).count() == 1
            assert db.query(TenantMember).count() == 1
    finally:
        engine.dispose()


def test_initial_admin_bootstrap_never_elevates_an_existing_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.security import hash_password
    from app.services.initial_admin_service import bootstrap_initial_admin_if_configured

    tenant_id = str(uuid4())
    monkeypatch.setattr(settings, "DEFAULT_TENANT_ID", tenant_id, raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_EMAIL", "owner@example.com", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_USERNAME", "owner", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", "correct-horse-battery-staple", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD_FILE", "", raising=False)

    engine, test_session = _build_test_session()
    try:
        with test_session() as db:
            db.add(Tenant(id=UUID(tenant_id), name=f"tenant-{tenant_id}", status="active", plan="basic"))
            db.add(
                User(
                    email="owner@example.com",
                    username="different-user",
                    password_hash=hash_password("another-valid-password"),
                    is_active=True,
                )
            )
            db.commit()

        with test_session() as db:
            with pytest.raises(RuntimeError) as excinfo:
                bootstrap_initial_admin_if_configured(db)

            assert "refusing automatic elevation" in str(excinfo.value)
            assert db.query(User).count() == 1
            assert db.query(TenantMember).count() == 0
    finally:
        engine.dispose()


def test_initial_admin_bootstrap_reads_password_from_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.services.initial_admin_service import bootstrap_initial_admin_if_configured

    password_file = tmp_path / "initial-admin-password.txt"
    password_file.write_text("correct-horse-battery-staple\n", encoding="utf-8")

    tenant_id = str(uuid4())
    monkeypatch.setattr(settings, "DEFAULT_TENANT_ID", tenant_id, raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_EMAIL", "owner@example.com", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_USERNAME", "owner", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", "", raising=False)
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD_FILE", str(password_file), raising=False)

    engine, test_session = _build_test_session()
    try:
        with test_session() as db:
            assert bootstrap_initial_admin_if_configured(db) is True
            user = db.query(User).filter(User.email == "owner@example.com").one()

            assert verify_password("correct-horse-battery-staple", user.password_hash) is True
    finally:
        engine.dispose()
