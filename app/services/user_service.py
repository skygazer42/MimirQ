"""
User service: register, authenticate, and tenant membership bootstrap.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import UserRoles
from app.core.security import hash_password, verify_password
from app.models.tenant import Tenant, TenantMember
from app.models.user import User


class UserService:
    @staticmethod
    def get_by_email(db: Session, email: str) -> User | None:
        return db.query(User).filter(User.email == email).first()

    @staticmethod
    def get_by_username(db: Session, username: str) -> User | None:
        return db.query(User).filter(User.username == username).first()

    @staticmethod
    def get_by_id(db: Session, user_id: str) -> User | None:
        try:
            user_uuid = UUID(str(user_id))
        except ValueError:
            return None
        return db.query(User).filter(User.id == user_uuid).first()

    @staticmethod
    def authenticate(db: Session, identifier: str, password: str) -> User:
        ident = (identifier or "").strip()
        ident_lower = ident.lower()
        user = (
            db.query(User)
            .filter((User.email == ident_lower) | (User.username == ident))
            .first()
        )
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User disabled")
        return user

    @staticmethod
    def create_user(db: Session, *, email: str, username: str, password: str) -> User:
        normalized_email = (email or "").strip().lower()
        normalized_username = (username or "").strip()

        if not normalized_email or not normalized_username:
            raise HTTPException(status_code=400, detail="Email and username are required")

        min_len = int(getattr(settings, "PASSWORD_MIN_LENGTH", 8))
        if len(password or "") < min_len:
            raise HTTPException(status_code=400, detail=f"Password must be at least {min_len} characters")

        if UserService.get_by_email(db, normalized_email):
            raise HTTPException(status_code=400, detail="Email already registered")
        if UserService.get_by_username(db, normalized_username):
            raise HTTPException(status_code=400, detail="Username already registered")

        try:
            password_hash = hash_password(password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        user = User(
            email=normalized_email,
            username=normalized_username,
            password_hash=password_hash,
            is_active=True,
        )
        db.add(user)
        db.flush()

        UserService.ensure_default_membership(db, user_id=str(user.id))

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def ensure_default_membership(db: Session, *, user_id: str) -> None:
        raw_tenant = str(getattr(settings, "DEFAULT_TENANT_ID", "") or "").strip()
        if not raw_tenant:
            raise HTTPException(status_code=500, detail="DEFAULT_TENANT_ID is not configured")
        try:
            tenant_id = UUID(raw_tenant)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="DEFAULT_TENANT_ID is invalid") from exc

        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).with_for_update().first()
        if not tenant:
            tenant = Tenant(
                id=tenant_id,
                name=f"tenant-{tenant_id}",
                status="active",
                plan="basic",
            )
            db.add(tenant)
            db.flush()

        if db.query(TenantMember.id).filter(TenantMember.tenant_id == tenant_id).first() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Initial registration is closed; contact an administrator",
            )
        db.add(
            TenantMember(
                tenant_id=tenant_id,
                user_id=user_id,
                role=UserRoles.OWNER,
                is_active=True,
                is_current=True,
            )
        )

    @staticmethod
    def get_default_tenant_member_count(db: Session) -> int:
        raw_tenant = str(getattr(settings, "DEFAULT_TENANT_ID", "") or "").strip()
        if not raw_tenant:
            raise HTTPException(status_code=500, detail="DEFAULT_TENANT_ID is not configured")
        try:
            tenant_id = UUID(raw_tenant)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="DEFAULT_TENANT_ID is invalid") from exc
        return int(
            db.query(TenantMember)
            .filter(TenantMember.tenant_id == tenant_id)
            .count()
        )

    @staticmethod
    def mark_login(db: Session, user: User) -> None:
        user.last_login_at = datetime.now(UTC)
        db.add(user)
        db.commit()

    @staticmethod
    def get_current_tenant_id(
        db: Session,
        *,
        user_id: str | None = None,
        _user_id: str | None = None,
    ) -> UUID | None:
        """
        Best-effort current tenant selection for token issuance.

        Prefers an explicit TenantMember marked as is_current; otherwise falls back to the most-recent
        membership row. Returns None when no membership exists.
        """
        uid_raw = user_id if user_id is not None else _user_id
        uid = str(uid_raw or "").strip()
        if not uid:
            return None

        member = (
            db.query(TenantMember)
            .filter(
                TenantMember.user_id == uid,
                TenantMember.is_current.is_(True),
            )
            .order_by(desc(TenantMember.updated_at), desc(TenantMember.created_at))
            .first()
        )
        if member and getattr(member, "tenant_id", None):
            return member.tenant_id

        member = (
            db.query(TenantMember)
            .filter(TenantMember.user_id == uid)
            .order_by(desc(TenantMember.updated_at), desc(TenantMember.created_at))
            .first()
        )
        if member and getattr(member, "tenant_id", None):
            return member.tenant_id

        return None
