"""
Document permission service (document-level ACL allowlist).

This mirrors dataset_service but is scoped to individual documents.
"""

from collections.abc import Sequence
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.document import DocumentPermission
from app.models.group_permissions import DocumentGroupPermission
from app.models.tenant import TenantMember
from app.models.tenant_group import TenantGroup


def get_document_partial_member_list(db: Session, tenant_id: UUID, document_id: UUID) -> list[str]:
    rows = (
        db.query(DocumentPermission.account_id)
        .filter(
            DocumentPermission.tenant_id == tenant_id,
            DocumentPermission.document_id == document_id,
        )
        .all()
    )
    return [account_id for (account_id,) in rows]


def clear_partial_member_list(db: Session, tenant_id: UUID, document_id: UUID) -> None:
    db.query(DocumentPermission).filter(
        DocumentPermission.tenant_id == tenant_id,
        DocumentPermission.document_id == document_id,
    ).delete(synchronize_session=False)


def update_partial_member_list(
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    member_ids: list[str],
    *,
    max_members: int = 200,
) -> None:
    """
    Replace the document allowlist with the provided member ids.

    Security:
    - validates that members exist in tenant_members (prevents typos silently opening access)
    - caps list size
    """
    normalized: list[str] = []
    seen: set[str] = set()
    for member_id in member_ids:
        mid = member_id.strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        normalized.append(mid)
        if max_members and len(normalized) >= max_members:
            break

    if normalized:
        rows = (
            db.query(TenantMember.user_id)
            .filter(
                TenantMember.tenant_id == tenant_id,
                TenantMember.user_id.in_(normalized),
            )
            .all()
        )
        found = {member_id for (member_id,) in rows}
        missing = [mid for mid in normalized if mid not in found]
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown tenant members: {', '.join(missing[:20])}")

    # Replace existing list.
    clear_partial_member_list(db, tenant_id, document_id)
    for mid in normalized:
        db.add(
            DocumentPermission(
                tenant_id=tenant_id,
                document_id=document_id,
                account_id=mid,
            )
        )


def get_document_partial_group_list(db: Session, tenant_id: UUID, document_id: UUID) -> list[UUID]:
    rows = (
        db.query(DocumentGroupPermission.group_id)
        .filter(
            DocumentGroupPermission.tenant_id == tenant_id,
            DocumentGroupPermission.document_id == document_id,
        )
        .all()
    )
    return [group_id for (group_id,) in rows]


def clear_partial_group_list(db: Session, tenant_id: UUID, document_id: UUID) -> None:
    db.query(DocumentGroupPermission).filter(
        DocumentGroupPermission.tenant_id == tenant_id,
        DocumentGroupPermission.document_id == document_id,
    ).delete(synchronize_session=False)


def update_partial_group_list(
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    group_ids: Sequence[UUID | str],
    *,
    max_groups: int = 200,
) -> None:
    normalized: list[UUID] = []
    seen: set[UUID] = set()
    for raw in group_ids:
        try:
            gid = raw if isinstance(raw, UUID) else UUID(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid group id") from exc
        if gid in seen:
            continue
        seen.add(gid)
        normalized.append(gid)
        if max_groups and len(normalized) >= max_groups:
            break

    if normalized:
        rows = (
            db.query(TenantGroup.id)
            .filter(
                TenantGroup.tenant_id == tenant_id,
                TenantGroup.id.in_(normalized),
            )
            .all()
        )
        found = {group_id for (group_id,) in rows}
        missing = [str(gid) for gid in normalized if gid not in found]
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown tenant groups: {', '.join(missing[:20])}")

    clear_partial_group_list(db, tenant_id, document_id)
    for gid in normalized:
        db.add(
            DocumentGroupPermission(
                tenant_id=tenant_id,
                document_id=document_id,
                group_id=gid,
            )
        )
