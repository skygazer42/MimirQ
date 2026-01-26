"""
Document permission service (document-level ACL allowlist).

This mirrors DatasetPermissionService but is scoped to individual documents.
"""

from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.document import DocumentPermission
from app.models.tenant import TenantMember


class DocumentPermissionService:
    @staticmethod
    def get_document_partial_member_list(db: Session, tenant_id: UUID, document_id: UUID) -> List[str]:
        rows = (
            db.query(DocumentPermission)
            .filter(
                DocumentPermission.tenant_id == tenant_id,
                DocumentPermission.document_id == document_id,
            )
            .all()
        )
        return [row.account_id for row in rows]

    @staticmethod
    def clear_partial_member_list(db: Session, tenant_id: UUID, document_id: UUID) -> None:
        db.query(DocumentPermission).filter(
            DocumentPermission.tenant_id == tenant_id,
            DocumentPermission.document_id == document_id,
        ).delete(synchronize_session=False)

    @staticmethod
    def update_partial_member_list(
        db: Session,
        tenant_id: UUID,
        document_id: UUID,
        member_ids: List[str],
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
        for member_id in member_ids or []:
            mid = str(member_id or "").strip()
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
            found = {row[0] for row in rows if row and row[0]}
            missing = [mid for mid in normalized if mid not in found]
            if missing:
                raise HTTPException(status_code=400, detail=f"Unknown tenant members: {', '.join(missing[:20])}")

        # Replace existing list.
        DocumentPermissionService.clear_partial_member_list(db, tenant_id, document_id)
        for mid in normalized:
            db.add(
                DocumentPermission(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    account_id=mid,
                )
            )

