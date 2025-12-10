"""
Dataset service: creation, permission checks, partial member management.
"""
from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.tenant import TenantMember


EDIT_ROLES = {"owner", "admin", "editor", "dataset_operator"}


class DatasetService:
    @staticmethod
    def ensure_member(db: Session, tenant_id: UUID, account_id: str) -> TenantMember:
        member = db.query(TenantMember).filter(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_id == account_id
        ).first()
        if not member:
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
    ) -> Dataset:
        member = DatasetService.ensure_member(db, tenant_id, owner_id)
        DatasetService._assert_edit_role(member)
        if permission != DatasetPermissionEnum.PARTIAL_MEMBERS:
            partial_members = []

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
            DatasetPermissionService.update_partial_member_list(db, tenant_id, dataset.id, partial_members, owner_id)

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
    ) -> Dataset:
        member = DatasetService.ensure_member(db, dataset.tenant_id, updater_id)
        DatasetService._assert_edit_role(member)

        if name is not None:
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
                    db, dataset.tenant_id, dataset.id, partial_members or [], updater_id
                )
            else:
                DatasetPermissionService.clear_partial_member_list(db, dataset.tenant_id, dataset.id)
        else:
            if dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS and partial_members is not None:
                DatasetPermissionService.update_partial_member_list(
                    db, dataset.tenant_id, dataset.id, partial_members, updater_id
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
        return bool(exists)

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
        operator_id: str
    ):
        # ensure all members belong to tenant
        for mid in member_ids:
            member = db.query(TenantMember).filter(
                TenantMember.tenant_id == tenant_id,
                TenantMember.user_id == mid
            ).first()
            if not member:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Member {mid} not in tenant")

        # remove existing
        db.query(DatasetPermission).filter(
            DatasetPermission.tenant_id == tenant_id,
            DatasetPermission.dataset_id == dataset_id
        ).delete()
        # add new
        for mid in member_ids:
            db.add(DatasetPermission(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                account_id=mid
            ))
        db.commit()

    @staticmethod
    def clear_partial_member_list(db: Session, tenant_id: UUID, dataset_id: UUID):
        db.query(DatasetPermission).filter(
            DatasetPermission.tenant_id == tenant_id,
            DatasetPermission.dataset_id == dataset_id
        ).delete()
        db.commit()
