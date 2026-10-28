"""Idempotent bootstrap for an environment-configured or generated initial owner."""

import json
import logging
import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import UserRoles
from app.core.security import hash_password
from app.models.tenant import Tenant, TenantMember
from app.models.user import User

_MAX_PASSWORD_FILE_BYTES = 4096
_DEFAULT_ADMIN_EMAIL = "admin@example.com"
_DEFAULT_ADMIN_USERNAME = "admin"
logger = logging.getLogger(__name__)


class InitialAdminBootstrapError(RuntimeError):
    """Raised when configured initial-owner bootstrap cannot be completed safely."""


@dataclass(frozen=True)
class _InitialAdminCredentials:
    email: str
    username: str
    password: str


def _read_password_file(raw_path: str) -> str:
    try:
        with Path(raw_path).expanduser().open("rb") as handle:
            payload = handle.read(_MAX_PASSWORD_FILE_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise InitialAdminBootstrapError("INITIAL_ADMIN_PASSWORD_FILE could not be read") from exc

    if len(payload) > _MAX_PASSWORD_FILE_BYTES:
        raise InitialAdminBootstrapError(
            f"INITIAL_ADMIN_PASSWORD_FILE must not exceed {_MAX_PASSWORD_FILE_BYTES} bytes"
        )
    try:
        return payload.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError as exc:
        raise InitialAdminBootstrapError("INITIAL_ADMIN_PASSWORD_FILE must contain UTF-8 text") from exc


def _load_credentials(config: object) -> _InitialAdminCredentials | None:
    raw_email = str(getattr(config, "INITIAL_ADMIN_EMAIL", "") or "").strip()
    username = str(getattr(config, "INITIAL_ADMIN_USERNAME", "") or "").strip()
    inline_password = str(getattr(config, "INITIAL_ADMIN_PASSWORD", "") or "")
    password_file = str(getattr(config, "INITIAL_ADMIN_PASSWORD_FILE", "") or "").strip()

    if not any((raw_email, username, inline_password, password_file)):
        return None
    if not raw_email or not username:
        raise InitialAdminBootstrapError(
            "INITIAL_ADMIN bootstrap requires INITIAL_ADMIN_EMAIL, INITIAL_ADMIN_USERNAME, "
            "and exactly one password source"
        )
    if bool(inline_password) == bool(password_file):
        raise InitialAdminBootstrapError(
            "INITIAL_ADMIN_PASSWORD and INITIAL_ADMIN_PASSWORD_FILE must configure exactly one password source"
        )

    password = inline_password if inline_password else _read_password_file(password_file)
    return _validated_credentials(config, email=raw_email, username=username, password=password)


def _validated_credentials(config: object, *, email: str, username: str, password: str) -> _InitialAdminCredentials:
    try:
        email = validate_email(email, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise InitialAdminBootstrapError("INITIAL_ADMIN_EMAIL must be a valid email address") from exc
    if len(email) > 255:
        raise InitialAdminBootstrapError("INITIAL_ADMIN_EMAIL must be a valid email address")
    if not 3 <= len(username) <= 64:
        raise InitialAdminBootstrapError("INITIAL_ADMIN_USERNAME must be between 3 and 64 characters")

    min_length = int(getattr(config, "PASSWORD_MIN_LENGTH", 8) or 8)
    if len(password) < min_length:
        raise InitialAdminBootstrapError(f"Initial admin password must be at least {min_length} characters")
    if len(password.encode("utf-8")) > 72:
        raise InitialAdminBootstrapError("Initial admin password cannot be longer than 72 bytes for bcrypt")

    return _InitialAdminCredentials(email=email, username=username, password=password)


def _default_credentials(config: object) -> _InitialAdminCredentials:
    path = Path(str(getattr(config, "INITIAL_ADMIN_CREDENTIALS_FILE", "") or "./data/initial-admin.json")).expanduser()
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        password_length = int(getattr(config, "PASSWORD_MIN_LENGTH", 8) or 8)
        password = secrets.token_urlsafe(max(24, (password_length * 3 + 3) // 4))
        credentials = _validated_credentials(
            config, email=_DEFAULT_ADMIN_EMAIL, username=_DEFAULT_ADMIN_USERNAME, password=password,
        )
        # Complete the private file before publishing it. A failed write must
        # never leave partial credentials at the path read by the next startup.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump({"username": credentials.username, "email": credentials.email, "password": credentials.password}, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # A hard link publishes atomically and refuses to replace an
            # existing file on both Windows and POSIX filesystems.
            os.link(temporary_path, path)
        except FileExistsError:
            # Reuse the file if a database is recreated; never rotate a saved
            # password or overwrite credentials from another startup attempt.
            if path.is_symlink():
                raise InitialAdminBootstrapError("Initial admin credential file must not be a symbolic link") from None
            with path.open("rb") as handle:
                payload = handle.read(_MAX_PASSWORD_FILE_BYTES + 1)
            if len(payload) > _MAX_PASSWORD_FILE_BYTES:
                raise InitialAdminBootstrapError("Initial admin credential file is too large") from None
            saved = json.loads(payload)
            if (
                not isinstance(saved, dict) or saved.get("username") != _DEFAULT_ADMIN_USERNAME
                or saved.get("email") != _DEFAULT_ADMIN_EMAIL or not isinstance(saved.get("password"), str)
            ):
                raise InitialAdminBootstrapError("Initial admin credential file is invalid") from None
            return _validated_credentials(
                config, email=saved["email"], username=saved["username"], password=saved["password"],
            )
        logger.info("Default administrator credentials saved to %s", path.resolve())
        return credentials
    except (OSError, ValueError, UnicodeError) as exc:
        raise InitialAdminBootstrapError("Initial admin credential file could not be read or written") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove temporary initial admin credential file %s", temporary_path)


def _default_tenant_id(config: object) -> UUID:
    raw_tenant_id = str(getattr(config, "DEFAULT_TENANT_ID", "") or "").strip()
    try:
        return UUID(raw_tenant_id)
    except ValueError as exc:
        raise InitialAdminBootstrapError("DEFAULT_TENANT_ID must be a valid UUID") from exc


def _matching_owner(db: Session, *, tenant_id: UUID, credentials: _InitialAdminCredentials) -> User | None:
    members = db.query(TenantMember).filter(TenantMember.tenant_id == tenant_id).all()
    if not members:
        return None

    for member in members:
        try:
            user_id = UUID(str(member.user_id or ""))
        except ValueError:
            continue
        user = db.query(User).filter(User.id == user_id).first()
        if (
            user is not None
            and str(user.email or "").lower() == credentials.email
            and str(user.username or "") == credentials.username
            and bool(user.is_active)
            and bool(member.is_active)
            and str(member.role or "").lower() == UserRoles.OWNER
        ):
            return user

    raise InitialAdminBootstrapError(
        "The default tenant already has a different member; remove INITIAL_ADMIN_* or use the existing owner"
    )


def _identity_conflicts(db: Session, credentials: _InitialAdminCredentials) -> bool:
    return (
        db.query(User.id).filter(func.lower(User.email) == credentials.email).first() is not None
        or db.query(User.id).filter(User.username == credentials.username).first() is not None
        or db.query(User.id).filter(func.lower(User.username) == credentials.email).first() is not None
        or db.query(User.id).filter(User.email == credentials.username.lower()).first() is not None
    )


def _lock_or_create_tenant(db: Session, tenant_id: UUID) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).with_for_update().first()
    if tenant is None:
        tenant = Tenant(
            id=tenant_id,
            name=f"tenant-{tenant_id}",
            status="active",
            plan="basic",
        )
        db.add(tenant)
        db.flush()
    return tenant


def _bootstrap_once(db: Session, *, tenant_id: UUID, credentials: _InitialAdminCredentials) -> bool:
    _lock_or_create_tenant(db, tenant_id)

    if _matching_owner(db, tenant_id=tenant_id, credentials=credentials) is not None:
        return False

    if _identity_conflicts(db, credentials):
        raise InitialAdminBootstrapError(
            "The configured INITIAL_ADMIN_* identity conflicts with an existing user; refusing automatic elevation"
        )

    user = User(
        email=credentials.email,
        username=credentials.username,
        password_hash=hash_password(credentials.password),
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(
        TenantMember(
            tenant_id=tenant_id,
            user_id=str(user.id),
            role=UserRoles.OWNER,
            is_active=True,
            is_current=True,
        )
    )
    db.commit()
    return True


def bootstrap_initial_admin_if_configured(db: Session, *, config: object = settings) -> bool:
    """Create a configured or default first owner without changing existing members."""
    credentials = _load_credentials(config)
    tenant_id = _default_tenant_id(config)
    use_default = credentials is None

    try:
        if use_default:
            tenant = _lock_or_create_tenant(db, tenant_id)
            if db.query(TenantMember.id).filter(TenantMember.tenant_id == tenant_id).first() is not None:
                return False
            if str(tenant.status or "").lower() != "active":
                raise InitialAdminBootstrapError("The default tenant is inactive; cannot create initial administrator")
            # Generate and persist credentials only after taking the workspace
            # lock. Other API replicas then see the committed owner and skip.
            credentials = _default_credentials(config)
        return _bootstrap_once(db, tenant_id=tenant_id, credentials=credentials)
    except IntegrityError as exc:
        # Concurrent API replicas can race while creating the tenant or account. Reconcile
        # after rollback; the winning replica is a valid idempotent result only when the
        # configured active owner now exists.
        db.rollback()
        if use_default and db.query(TenantMember.id).filter(TenantMember.tenant_id == tenant_id).first() is not None:
            return False
        if _matching_owner(db, tenant_id=tenant_id, credentials=credentials) is not None:
            return False
        raise InitialAdminBootstrapError("Initial admin bootstrap conflicted with another database writer") from exc
    except Exception:
        db.rollback()
        raise
