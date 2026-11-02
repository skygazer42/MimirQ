"""Local user registration, authentication and tenant membership."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.core.constants import UserRoles
from app.core.exceptions import AuthenticationError, AuthorizationError, BadRequestError, ConfigError, ConflictError
from app.core.security import hash_password, verify_password
from app.models.tenant import Tenant, TenantMember
from app.models.user import User


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()


def get_user_by_id(db: Session, user_id: str) -> User | None:
    # The account identifier comes from a token; malformed IDs retain the existing not-found behavior.
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        return None
    return db.query(User).filter(User.id == user_uuid).first()


def authenticate_user(db: Session, identifier: str, password: str) -> User:
    identifier = identifier.strip()
    users = db.query(User).filter((User.email == identifier.lower()) | (User.username == identifier)).all()
    if len(users) != 1:
        raise AuthenticationError("Invalid credentials")
    user = users[0]
    if not verify_password(password, user.password_hash):
        raise AuthenticationError("Invalid credentials")
    if not user.is_active:
        raise AuthorizationError("User disabled")
    return user


def create_user(
    db: Session,
    *,
    email: str,
    username: str,
    password: str,
    password_min_length: int,
    default_tenant_id: str,
) -> User:
    email = email.strip().lower()
    username = username.strip()
    if not email or not username:
        raise BadRequestError("Email and username are required")
    if len(password) < password_min_length:
        raise BadRequestError(f"Password must be at least {password_min_length} characters")

    if get_user_by_email(db, email):
        raise BadRequestError("Email already registered")
    if db.query(User.id).filter(func.lower(User.username) == email).first():
        raise BadRequestError("Email already registered")
    if get_user_by_username(db, username):
        raise BadRequestError("Username already registered")
    if db.query(User.id).filter(User.email == username.lower()).first():
        raise BadRequestError("Username already registered")

    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc

    user = User(email=email, username=username, password_hash=password_hash, is_active=True)
    db.add(user)
    db.flush()
    ensure_default_membership(db, user_id=str(user.id), default_tenant_id=default_tenant_id)
    db.commit()
    db.refresh(user)
    return user


def _parse_default_tenant_id(value: str) -> UUID:
    value = value.strip()
    if not value:
        raise ConfigError("DEFAULT_TENANT_ID is not configured")
    try:
        return UUID(value)
    except ValueError as exc:
        raise ConfigError("DEFAULT_TENANT_ID is invalid") from exc


def ensure_default_membership(db: Session, *, user_id: str, default_tenant_id: str) -> None:
    tenant_id = _parse_default_tenant_id(default_tenant_id)
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).with_for_update().first()
    if not tenant:
        tenant = Tenant(id=tenant_id, name=f"tenant-{tenant_id}", status="active", plan="basic")
        db.add(tenant)
        db.flush()

    if db.query(TenantMember.id).filter(TenantMember.tenant_id == tenant_id).first() is not None:
        raise ConflictError("Initial registration is closed; contact an administrator")
    db.add(
        TenantMember(
            tenant_id=tenant_id,
            user_id=user_id,
            role=UserRoles.OWNER,
            is_active=True,
            is_current=True,
        )
    )


def get_default_tenant_member_count(db: Session, *, default_tenant_id: str) -> int:
    tenant_id = _parse_default_tenant_id(default_tenant_id)
    return db.query(TenantMember).filter(TenantMember.tenant_id == tenant_id).count()


def mark_login(db: Session, user: User) -> None:
    user.last_login_at = datetime.now(UTC)
    db.add(user)
    db.commit()


def get_current_tenant_id(db: Session, *, user_id: str) -> UUID | None:
    """Prefer an active current membership, then the newest active membership."""
    member = (
        db.query(TenantMember)
        .join(Tenant, Tenant.id == TenantMember.tenant_id)
        .filter(
            TenantMember.user_id == user_id,
            TenantMember.is_active.is_(True),
            func.lower(Tenant.status) == "active",
        )
        # IS TRUE keeps legacy NULL flags in the non-current group on both PostgreSQL and SQLite.
        .order_by(
            TenantMember.is_current.is_(True).desc(),
            desc(TenantMember.updated_at),
            desc(TenantMember.created_at),
        )
        .first()
    )
    return member.tenant_id if member else None
