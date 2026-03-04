"""
Dataset service: creation, permission checks, partial member management.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.constants import UserRoles
from app.core.env import is_production_env
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.group_permissions import DatasetGroupPermission
from app.models.tenant import Tenant, TenantMember
from app.models.tenant_group import TenantGroup, TenantGroupMember

EDIT_ROLES = UserRoles.EDIT_ROLES


class DatasetService:
    @staticmethod
    def ensure_member(db: Session, tenant_id: UUID, account_id: str) -> TenantMember:
        member = db.query(TenantMember).filter(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_id == account_id
        ).first()
        if not member:
            if not is_production_env():
                # Dev-friendly bootstrap: create tenant + membership on first use.
                tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
                if not tenant:
                    db.add(
                        Tenant(
                            id=tenant_id,
                            name=f"tenant-{tenant_id}",
                            status="active",
                            plan="basic",
                        )
                    )
                member = TenantMember(
                    tenant_id=tenant_id,
                    user_id=account_id,
                    role="owner",
                    is_current=True,
                )
                db.add(member)
                db.commit()
                db.refresh(member)
                return member
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a tenant member")
        return member

    @staticmethod
    def _assert_edit_role(member: TenantMember):
        role = (member.role or "").lower()
        if role not in EDIT_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission to manage dataset")

    @staticmethod
    def get_dataset(db: Session, tenant_id: UUID, dataset_id: UUID) -> Dataset:
        dataset = db.query(Dataset).filter(
            Dataset.id == dataset_id,
            Dataset.tenant_id == tenant_id
        ).first()
        if not dataset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
        return dataset

    @staticmethod
    def create_dataset(
        db: Session,
        tenant_id: UUID,
        name: str,
        description: Optional[str],
        permission: DatasetPermissionEnum,
        owner_id: str,
        partial_members: Optional[List[str]] = None,
        partial_groups: Optional[List[UUID]] = None,
    ) -> Dataset:
        member = DatasetService.ensure_member(db, tenant_id, owner_id)
        DatasetService._assert_edit_role(member)
        if permission != DatasetPermissionEnum.PARTIAL_MEMBERS:
            partial_members = []
            partial_groups = []

        exists = (
            db.query(Dataset.id)
            .filter(Dataset.tenant_id == tenant_id, Dataset.name == name)
            .first()
        )
        if exists:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dataset name already exists")

        dataset = Dataset(
            tenant_id=tenant_id,
            name=name,
            description=description,
            permission=permission,
            owner_id=owner_id
        )
        db.add(dataset)
        db.commit()
        db.refresh(dataset)

        if permission == DatasetPermissionEnum.PARTIAL_MEMBERS and partial_members:
            DatasetPermissionService.update_partial_member_list(db, tenant_id, dataset.id, partial_members)
        if permission == DatasetPermissionEnum.PARTIAL_MEMBERS and partial_groups:
            DatasetGroupPermissionService.update_partial_group_list(db, tenant_id, dataset.id, partial_groups)

        return dataset

    @staticmethod
    def update_dataset(
        db: Session,
        dataset: Dataset,
        updater_id: str,
        name: Optional[str],
        description: Optional[str],
        permission: Optional[DatasetPermissionEnum],
        partial_members: Optional[List[str]],
        partial_groups: Optional[List[UUID]],
    ) -> Dataset:
        member = DatasetService.ensure_member(db, dataset.tenant_id, updater_id)
        DatasetService._assert_edit_role(member)

        if name is not None and name != dataset.name:
            exists = (
                db.query(Dataset.id)
                .filter(Dataset.tenant_id == dataset.tenant_id, Dataset.name == name, Dataset.id != dataset.id)
                .first()
            )
            if exists:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dataset name already exists")
            dataset.name = name
        if description is not None:
            dataset.description = description
        if permission is not None:
            dataset.permission = permission

        db.commit()
        db.refresh(dataset)

        # handle partial members update
        if permission is not None:
            if permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
                DatasetPermissionService.update_partial_member_list(
                    db, dataset.tenant_id, dataset.id, partial_members or []
                )
                DatasetGroupPermissionService.update_partial_group_list(
                    db, dataset.tenant_id, dataset.id, partial_groups or []
                )
            else:
                DatasetPermissionService.clear_partial_member_list(db, dataset.tenant_id, dataset.id)
                DatasetGroupPermissionService.clear_partial_group_list(db, dataset.tenant_id, dataset.id)
        else:
            if dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS and partial_members is not None:
                DatasetPermissionService.update_partial_member_list(
                    db, dataset.tenant_id, dataset.id, partial_members
                )
            if dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS and partial_groups is not None:
                DatasetGroupPermissionService.update_partial_group_list(
                    db, dataset.tenant_id, dataset.id, partial_groups
                )

        return dataset

    @staticmethod
    def check_dataset_permission(
        db: Session,
        dataset: Dataset,
        account_id: str,
    ) -> bool:
        """
        Read access: owner OR all_team_members OR partial match OR has explicit record.
        """
        if dataset.owner_id == account_id:
            return True
        if dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS:
            return True
        if dataset.permission == DatasetPermissionEnum.ONLY_ME:
            return False
        # partial_members
        exists = db.query(DatasetPermission).filter(
            DatasetPermission.dataset_id == dataset.id,
            DatasetPermission.tenant_id == dataset.tenant_id,
            DatasetPermission.account_id == account_id
        ).first()
        if exists:
            return True

        # Group-based allowlist (enterprise): allow when any of the account's tenant groups
        # is granted access to the dataset.
        group_rows = (
            db.query(TenantGroupMember.group_id)
            .filter(
                TenantGroupMember.tenant_id == dataset.tenant_id,
                TenantGroupMember.user_id == account_id,
            )
            .all()
        )
        group_ids = [row[0] for row in group_rows if row and row[0]]
        if not group_ids:
            return False

        group_perm = (
            db.query(DatasetGroupPermission.id)
            .filter(
                DatasetGroupPermission.tenant_id == dataset.tenant_id,
                DatasetGroupPermission.dataset_id == dataset.id,
                DatasetGroupPermission.group_id.in_(group_ids),
            )
            .first()
        )
        return bool(group_perm)

    @staticmethod
    def assert_dataset_readable(db: Session, dataset: Dataset, account_id: str):
        DatasetService.ensure_member(db, dataset.tenant_id, account_id)
        if not DatasetService.check_dataset_permission(db, dataset, account_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No dataset access")

    @staticmethod
    def assert_dataset_writable(db: Session, dataset: Dataset, account_id: str):
        member = DatasetService.ensure_member(db, dataset.tenant_id, account_id)
        DatasetService._assert_edit_role(member)
        if dataset.owner_id == account_id:
            return
        if dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS:
            return
        if dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
            exists = db.query(DatasetPermission).filter(
                DatasetPermission.dataset_id == dataset.id,
                DatasetPermission.tenant_id == dataset.tenant_id,
                DatasetPermission.account_id == account_id
            ).first()
            if exists:
                return

            group_rows = (
                db.query(TenantGroupMember.group_id)
                .filter(
                    TenantGroupMember.tenant_id == dataset.tenant_id,
                    TenantGroupMember.user_id == account_id,
                )
                .all()
            )
            group_ids = [row[0] for row in group_rows if row and row[0]]
            if group_ids:
                group_perm = (
                    db.query(DatasetGroupPermission.id)
                    .filter(
                        DatasetGroupPermission.tenant_id == dataset.tenant_id,
                        DatasetGroupPermission.dataset_id == dataset.id,
                        DatasetGroupPermission.group_id.in_(group_ids),
                    )
                    .first()
                )
                if group_perm:
                    return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No dataset write permission")


class DatasetPermissionService:
    @staticmethod
    def get_dataset_partial_member_list(db: Session, tenant_id: UUID, dataset_id: UUID) -> List[str]:
        rows = db.query(DatasetPermission).filter(
            DatasetPermission.tenant_id == tenant_id,
            DatasetPermission.dataset_id == dataset_id
        ).all()
        return [row.account_id for row in rows]

    @staticmethod
    def update_partial_member_list(
        db: Session,
        tenant_id: UUID,
        dataset_id: UUID,
        member_ids: List[str],
    ):
        normalized_member_ids: list[str] = []
        seen: set[str] = set()
        for member_id in member_ids:
            mid = str(member_id or "").strip()
            if not mid or mid in seen:
                continue
            seen.add(mid)
            normalized_member_ids.append(mid)

        if normalized_member_ids:
            rows = (
                db.query(TenantMember.user_id)
                .filter(
                    TenantMember.tenant_id == tenant_id,
                    TenantMember.user_id.in_(normalized_member_ids),
                )
                .all()
            )
            found = {row[0] for row in rows}
            missing = [mid for mid in normalized_member_ids if mid not in found]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Member(s) not in tenant: {', '.join(missing)}",
                )

        db.query(DatasetPermission).filter(
            DatasetPermission.tenant_id == tenant_id,
            DatasetPermission.dataset_id == dataset_id,
        ).delete(synchronize_session=False)

        if normalized_member_ids:
            db.add_all(
                [
                    DatasetPermission(
                        tenant_id=tenant_id,
                        dataset_id=dataset_id,
                        account_id=mid,
                    )
                    for mid in normalized_member_ids
                ]
            )
        db.commit()

    @staticmethod
    def clear_partial_member_list(db: Session, tenant_id: UUID, dataset_id: UUID):
        db.query(DatasetPermission).filter(
            DatasetPermission.tenant_id == tenant_id,
            DatasetPermission.dataset_id == dataset_id
        ).delete()
        db.commit()


class DatasetGroupPermissionService:
    @staticmethod
    def get_dataset_partial_group_list(db: Session, tenant_id: UUID, dataset_id: UUID) -> List[UUID]:
        rows = (
            db.query(DatasetGroupPermission.group_id)
            .filter(
                DatasetGroupPermission.tenant_id == tenant_id,
                DatasetGroupPermission.dataset_id == dataset_id,
            )
            .all()
        )
        return [row[0] for row in rows if row and row[0]]

    @staticmethod
    def update_partial_group_list(
        db: Session,
        tenant_id: UUID,
        dataset_id: UUID,
        group_ids: List[UUID],
        *,
        max_groups: int = 200,
    ) -> None:
        normalized: list[UUID] = []
        seen: set[UUID] = set()
        for raw in group_ids or []:
            try:
                gid = UUID(str(raw))
            except Exception as exc:
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
            found = {row[0] for row in rows if row and row[0]}
            missing = [str(gid) for gid in normalized if gid not in found]
            if missing:
                raise HTTPException(status_code=400, detail=f"Unknown tenant groups: {', '.join(missing[:20])}")

        db.query(DatasetGroupPermission).filter(
            DatasetGroupPermission.tenant_id == tenant_id,
            DatasetGroupPermission.dataset_id == dataset_id,
        ).delete(synchronize_session=False)

        if normalized:
            db.add_all(
                [
                    DatasetGroupPermission(
                        tenant_id=tenant_id,
                        dataset_id=dataset_id,
                        group_id=gid,
                    )
                    for gid in normalized
                ]
            )
        db.commit()

    @staticmethod
    def clear_partial_group_list(db: Session, tenant_id: UUID, dataset_id: UUID) -> None:
        db.query(DatasetGroupPermission).filter(
            DatasetGroupPermission.tenant_id == tenant_id,
            DatasetGroupPermission.dataset_id == dataset_id,
        ).delete(synchronize_session=False)
        db.commit()
