import json
from types import SimpleNamespace
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


def test_blank_env_keeps_credentials_out_of_configuration_until_startup(monkeypatch: pytest.MonkeyPatch) -> None:
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


@pytest.fixture
def default_admin_config(tmp_path):
    return SimpleNamespace(
        DEFAULT_TENANT_ID=str(uuid4()), INITIAL_ADMIN_EMAIL="", INITIAL_ADMIN_USERNAME="",
        INITIAL_ADMIN_PASSWORD="", INITIAL_ADMIN_PASSWORD_FILE="", PASSWORD_MIN_LENGTH=8,
        INITIAL_ADMIN_CREDENTIALS_FILE=str(tmp_path / "credentials" / "initial-admin.json"),
    )


def test_blank_admin_configuration_creates_default_owner_with_saved_random_credentials(default_admin_config, caplog):
    from pathlib import Path

    from app.services.initial_admin_service import bootstrap_initial_admin_if_configured

    engine, sessions = _build_test_session()
    try:
        with sessions() as db:
            assert bootstrap_initial_admin_if_configured(db, config=default_admin_config) is True
            credentials = json.loads(Path(default_admin_config.INITIAL_ADMIN_CREDENTIALS_FILE).read_text())
            user = db.query(User).one()
            member = db.query(TenantMember).one()
            assert credentials["username"] == user.username == "admin"
            assert credentials["email"] == user.email == "admin@example.com"
            assert len(credentials["password"]) >= 32
            assert verify_password(credentials["password"], user.password_hash)
            assert member.user_id == str(user.id)
            assert member.role == "owner"
            assert member.is_active is True
            assert credentials["password"] not in caplog.text
    finally:
        engine.dispose()


def test_default_admin_restarts_do_not_rotate_password_or_recreate_missing_credentials(default_admin_config):
    from pathlib import Path

    from app.services.initial_admin_service import bootstrap_initial_admin_if_configured

    engine, sessions = _build_test_session()
    try:
        with sessions() as db:
            assert bootstrap_initial_admin_if_configured(db, config=default_admin_config) is True
            original_hash = db.query(User).one().password_hash
        path = Path(default_admin_config.INITIAL_ADMIN_CREDENTIALS_FILE)
        original_file = path.read_bytes()
        with sessions() as db:
            assert bootstrap_initial_admin_if_configured(db, config=default_admin_config) is False
            assert path.read_bytes() == original_file
            path.unlink()
            assert bootstrap_initial_admin_if_configured(db, config=default_admin_config) is False
            assert not path.exists()
            assert db.query(User).one().password_hash == original_hash
            assert db.query(User).count() == 1
    finally:
        engine.dispose()


def test_default_admin_does_not_override_existing_members_or_elevate_identities(default_admin_config):
    from pathlib import Path

    from app.core.security import hash_password
    from app.services.initial_admin_service import bootstrap_initial_admin_if_configured

    engine, sessions = _build_test_session()
    try:
        with sessions() as db:
            tenant_id = UUID(default_admin_config.DEFAULT_TENANT_ID)
            db.add(Tenant(id=tenant_id, name="existing", status="active"))
            user = User(email="admin@example.com", username="admin", password_hash=hash_password("existing-password"))
            db.add(user)
            db.flush()
            db.add(TenantMember(tenant_id=tenant_id, user_id=str(user.id), role="viewer", is_active=True))
            db.commit()
            assert bootstrap_initial_admin_if_configured(db, config=default_admin_config) is False
            assert db.query(TenantMember).one().role == "viewer"
            assert verify_password("existing-password", db.query(User).one().password_hash)
            assert not Path(default_admin_config.INITIAL_ADMIN_CREDENTIALS_FILE).exists()
    finally:
        engine.dispose()


def test_default_admin_reuses_saved_credentials_after_database_recreation(default_admin_config):
    from pathlib import Path

    from app.services.initial_admin_service import bootstrap_initial_admin_if_configured

    path = Path(default_admin_config.INITIAL_ADMIN_CREDENTIALS_FILE)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "email": "admin@example.com", "username": "admin", "password": "previously-generated-password-for-admin",
    }))
    engine, sessions = _build_test_session()
    try:
        with sessions() as db:
            assert bootstrap_initial_admin_if_configured(db, config=default_admin_config) is True
            assert verify_password("previously-generated-password-for-admin", db.query(User).one().password_hash)
    finally:
        engine.dispose()


def test_unwritable_default_credentials_prevent_inaccessible_admin_creation(default_admin_config, tmp_path):
    from app.services.initial_admin_service import InitialAdminBootstrapError, bootstrap_initial_admin_if_configured

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("file")
    default_admin_config.INITIAL_ADMIN_CREDENTIALS_FILE = str(blocker / "admin.json")
    engine, sessions = _build_test_session()
    try:
        with sessions() as db:
            with pytest.raises(InitialAdminBootstrapError):
                bootstrap_initial_admin_if_configured(db, config=default_admin_config)
            assert db.query(User).count() == 0
            assert db.query(TenantMember).count() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("failure_point", ["write", "fsync"])
def test_failed_default_credential_write_can_be_retried(default_admin_config, monkeypatch, failure_point):
    from pathlib import Path

    from app.services import initial_admin_service as service

    def fail_write(_payload, handle):
        handle.write("{")
        raise OSError("Temporary storage failure")

    def fail_fsync(_descriptor):
        raise OSError("Temporary storage failure")

    path = Path(default_admin_config.INITIAL_ADMIN_CREDENTIALS_FILE)
    engine, sessions = _build_test_session()
    try:
        with sessions() as db:
            with monkeypatch.context() as fault:
                if failure_point == "write":
                    fault.setattr(service.json, "dump", fail_write)
                else:
                    fault.setattr(service.os, "fsync", fail_fsync)
                with pytest.raises(service.InitialAdminBootstrapError):
                    service.bootstrap_initial_admin_if_configured(db, config=default_admin_config)
            assert db.query(User).count() == 0
            assert db.query(TenantMember).count() == 0
            assert not path.exists()
            assert list(path.parent.iterdir()) == []

            assert service.bootstrap_initial_admin_if_configured(db, config=default_admin_config) is True
            saved = json.loads(path.read_text(encoding="utf-8"))
            assert verify_password(saved["password"], db.query(User).one().password_hash)
            assert db.query(TenantMember).one().role == "owner"
            assert list(path.parent.iterdir()) == [path]
    finally:
        engine.dispose()


def test_different_installations_get_different_default_admin_passwords(default_admin_config, tmp_path):
    from pathlib import Path

    from app.services.initial_admin_service import bootstrap_initial_admin_if_configured

    passwords = []
    for index in range(2):
        default_admin_config.INITIAL_ADMIN_CREDENTIALS_FILE = str(tmp_path / str(index) / "admin.json")
        engine, sessions = _build_test_session()
        try:
            with sessions() as db:
                assert bootstrap_initial_admin_if_configured(db, config=default_admin_config) is True
                passwords.append(json.loads(Path(default_admin_config.INITIAL_ADMIN_CREDENTIALS_FILE).read_text())["password"])
        finally:
            engine.dispose()
    assert passwords[0] != passwords[1]


def test_explicit_admin_configuration_takes_priority_over_default_credentials(default_admin_config):
    from pathlib import Path

    from app.services.initial_admin_service import bootstrap_initial_admin_if_configured

    default_admin_config.INITIAL_ADMIN_EMAIL = "operator@example.com"
    default_admin_config.INITIAL_ADMIN_USERNAME = "operator"
    default_admin_config.INITIAL_ADMIN_PASSWORD = "configured-operator-password"
    engine, sessions = _build_test_session()
    try:
        with sessions() as db:
            assert bootstrap_initial_admin_if_configured(db, config=default_admin_config) is True
            assert db.query(User).one().username == "operator"
            assert verify_password("configured-operator-password", db.query(User).one().password_hash)
            assert not Path(default_admin_config.INITIAL_ADMIN_CREDENTIALS_FILE).exists()
    finally:
        engine.dispose()


@pytest.mark.parametrize("contents", ["{broken json", '{"username":"admin","email":"admin@example.com","password":"short"}'])
def test_invalid_saved_default_credentials_do_not_create_an_unknown_admin(default_admin_config, contents):
    from pathlib import Path

    from app.services.initial_admin_service import InitialAdminBootstrapError, bootstrap_initial_admin_if_configured

    path = Path(default_admin_config.INITIAL_ADMIN_CREDENTIALS_FILE)
    path.parent.mkdir(parents=True)
    path.write_text(contents)
    engine, sessions = _build_test_session()
    try:
        with sessions() as db:
            with pytest.raises(InitialAdminBootstrapError):
                bootstrap_initial_admin_if_configured(db, config=default_admin_config)
            assert db.query(User).count() == 0
            assert db.query(TenantMember).count() == 0
            assert path.read_text() == contents
    finally:
        engine.dispose()


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
