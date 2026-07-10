"""
Tenant group service (enterprise directory primitive).

This is intentionally simple:
- tenant-scoped groups
- user_id is a string (matches current tenant_members.user_id model)
"""


import contextlib
from collections.abc import Iterable
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.request_state import get_request_state
from app.models.tenant import TenantMember
from app.models.tenant_group import TenantGroup, TenantGroupMember


def _normalize_member_ids(member_ids: Iterable[str], *, max_items: int = 200) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in member_ids or []:
        mid = str(raw or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        if len(mid) > 255:
            raise HTTPException(status_code=400, detail="member id too long (max=255)")
        out.append(mid)
        if max_items and len(out) >= max_items:
            break
    return out


class TenantGroupService:
    @staticmethod
    def resolve_account_group_ids(db: Session, *, tenant_id: UUID, account_id: str) -> set[UUID]:
        """
        Resolve tenant-scoped group ids for an account (best-effort cached per request).

        Cache is stored on `request.state` to avoid repeated DB queries across multiple
        permission checks in the same API request.
        """
        uid = (str(account_id or "")).strip()
        if not uid:
            return set()

        state = get_request_state()
        cache_key = (tenant_id, uid)
        if state is not None:
            cached = None
            with contextlib.suppress(Exception):
                cache = getattr(state, "_mimirq_group_ids_cache", None)
                if isinstance(cache, dict):
                    cached = cache.get(cache_key)
            if isinstance(cached, set):
                return cached
            if isinstance(cached, (list, tuple)):
                return {gid for gid in cached if gid}

        rows = (
            db.query(TenantGroupMember.group_id)
            .filter(
                TenantGroupMember.tenant_id == tenant_id,
                TenantGroupMember.user_id == uid,
            )
            .all()
        )
        group_ids = {row[0] for row in rows if row and row[0]}

        if state is not None:
            with contextlib.suppress(Exception):
                cache = getattr(state, "_mimirq_group_ids_cache", None)
                if not isinstance(cache, dict):
                    cache = {}
                    state._mimirq_group_ids_cache = cache
                cache[cache_key] = group_ids

        return group_ids

    @staticmethod
    def list_groups(db: Session, *, tenant_id: UUID, skip: int = 0, limit: int = 200) -> tuple[int, list[TenantGroup]]:
        q = db.query(TenantGroup).filter(TenantGroup.tenant_id == tenant_id)
        total = int(q.count())
        items = (
            q.order_by(TenantGroup.name.asc())
            .offset(max(0, int(skip or 0)))
            .limit(max(1, min(int(limit or 0), 1000)))
            .all()
        )
        return total, items

    @staticmethod
    def get_group(db: Session, *, tenant_id: UUID, group_id: UUID) -> TenantGroup:
        group = (
            db.query(TenantGroup)
            .filter(TenantGroup.tenant_id == tenant_id, TenantGroup.id == group_id)
            .first()
        )
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
        return group

    @staticmethod
    def create_group(db: Session, *, tenant_id: UUID, name: str, external_id: str | None = None) -> TenantGroup:
        n = str(name or "").strip()
        if not n:
            raise HTTPException(status_code=400, detail="name is required")
        if len(n) > 255:
            raise HTTPException(status_code=400, detail="name too long (max=255)")

        ext = str(external_id or "").strip() or None
        if ext is not None and len(ext) > 255:
            raise HTTPException(status_code=400, detail="external_id too long (max=255)")

        exists = (
            db.query(TenantGroup.id)
            .filter(TenantGroup.tenant_id == tenant_id, TenantGroup.name == n)
            .first()
        )
        if exists:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Group name already exists")

        if ext is not None:
            ext_exists = (
                db.query(TenantGroup.id)
                .filter(TenantGroup.tenant_id == tenant_id, TenantGroup.external_id == ext)
                .first()
            )
            if ext_exists:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Group external_id already exists")

        group = TenantGroup(
            tenant_id=tenant_id,
            name=n,
            external_id=ext,
        )
        db.add(group)
        db.commit()
        db.refresh(group)
        return group

    @staticmethod
    def update_group(
        db: Session,
        *,
        tenant_id: UUID,
        group_id: UUID,
        name: str | None,
        external_id: str | None,
    ) -> TenantGroup:
        group = TenantGroupService.get_group(db, tenant_id=tenant_id, group_id=group_id)

        if name is not None:
            n = str(name or "").strip()
            if not n:
                raise HTTPException(status_code=400, detail="name is required")
            if len(n) > 255:
                raise HTTPException(status_code=400, detail="name too long (max=255)")
            if n != group.name:
                exists = (
                    db.query(TenantGroup.id)
                    .filter(TenantGroup.tenant_id == tenant_id, TenantGroup.name == n, TenantGroup.id != group_id)
                    .first()
                )
                if exists:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Group name already exists")
                group.name = n

        if external_id is not None:
            ext = str(external_id or "").strip() or None
            if ext is not None and len(ext) > 255:
                raise HTTPException(status_code=400, detail="external_id too long (max=255)")
            if ext is not None:
                ext_exists = (
                    db.query(TenantGroup.id)
                    .filter(
                        TenantGroup.tenant_id == tenant_id,
                        TenantGroup.external_id == ext,
                        TenantGroup.id != group_id,
                    )
                    .first()
                )
                if ext_exists:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Group external_id already exists")
            group.external_id = ext

        db.commit()
        db.refresh(group)
        return group

    @staticmethod
    def delete_group(db: Session, *, tenant_id: UUID, group_id: UUID) -> None:
        group = TenantGroupService.get_group(db, tenant_id=tenant_id, group_id=group_id)
        db.delete(group)
        db.commit()

    @staticmethod
    def list_members(
        db: Session,
        *,
        tenant_id: UUID,
        group_id: UUID,
        skip: int = 0,
        limit: int = 500,
    ) -> tuple[int, list[TenantGroupMember]]:
        TenantGroupService.get_group(db, tenant_id=tenant_id, group_id=group_id)

        q = (
            db.query(TenantGroupMember)
            .filter(
                TenantGroupMember.tenant_id == tenant_id,
                TenantGroupMember.group_id == group_id,
            )
        )
        total = int(q.count())
        items = (
            q.order_by(TenantGroupMember.created_at.desc())
            .offset(max(0, int(skip or 0)))
            .limit(max(1, min(int(limit or 0), 1000)))
            .all()
        )
        return total, items

    @staticmethod
    def add_members(
        db: Session,
        *,
        tenant_id: UUID,
        group_id: UUID,
        member_ids: list[str],
    ) -> int:
        TenantGroupService.get_group(db, tenant_id=tenant_id, group_id=group_id)

        normalized = _normalize_member_ids(member_ids or [], max_items=200)
        if not normalized:
            return 0

        # Validate tenant membership (fail closed).
        rows = (
            db.query(TenantMember.user_id)
            .filter(
                TenantMember.tenant_id == tenant_id,
                TenantMember.user_id.in_(normalized),
            )
            .all()
        )
        found = {row[0] for row in rows if row and row[0]}
        missing = [mid for mid in normalized if mid not in found]
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown tenant members: {', '.join(missing[:20])}")

        # Avoid duplicates.
        existing_rows = (
            db.query(TenantGroupMember.user_id)
            .filter(
                TenantGroupMember.tenant_id == tenant_id,
                TenantGroupMember.group_id == group_id,
                TenantGroupMember.user_id.in_(normalized),
            )
            .all()
        )
        existing = {row[0] for row in existing_rows if row and row[0]}
        to_add = [mid for mid in normalized if mid not in existing]
        if not to_add:
            return 0

        for mid in to_add:
            db.add(
                TenantGroupMember(
                    tenant_id=tenant_id,
                    group_id=group_id,
                    user_id=mid,
                )
            )
        db.commit()
        return int(len(to_add))

    @staticmethod
    def remove_members(
        db: Session,
        *,
        tenant_id: UUID,
        group_id: UUID,
        member_ids: list[str],
    ) -> int:
        TenantGroupService.get_group(db, tenant_id=tenant_id, group_id=group_id)

        normalized = _normalize_member_ids(member_ids or [], max_items=200)
        if not normalized:
            return 0

        deleted = (
            db.query(TenantGroupMember)
            .filter(
                TenantGroupMember.tenant_id == tenant_id,
                TenantGroupMember.group_id == group_id,
                TenantGroupMember.user_id.in_(normalized),
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        return int(deleted or 0)
