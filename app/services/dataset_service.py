"""
Dataset service: creation, permission checks, partial member management.
"""

import ipaddress
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import UserRoles
from app.core.env import is_production_env
from app.core.request_state import get_request_state
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.group_permissions import DatasetGroupPermission
from app.models.tenant import Tenant, TenantMember
from app.models.tenant_group import TenantGroup
from app.services.audit_log_service import audit_log_event
from app.services.authz_prometheus_metrics import observe_group_permission_check
from app.services.tenant_group_service import TenantGroupService

EDIT_ROLES = UserRoles.EDIT_ROLES


class DatasetService:
    @staticmethod
    def _default_tenant_id() -> UUID | None:
        raw_tenant_id = str(getattr(settings, "DEFAULT_TENANT_ID", "") or "").strip()
        if not raw_tenant_id:
            return None
        try:
            return UUID(raw_tenant_id)
        except ValueError:
            return None

    @staticmethod
    def _is_loopback_client(host: object) -> bool:
        value = str(host or "").strip().lower()
        if not value:
            return False
        if value in {"localhost", "localhost.localdomain"}:
            return True
        try:
            return bool(ipaddress.ip_address(value).is_loopback)
        except ValueError:
            return False

    @staticmethod
    def _allow_local_owner_bootstrap(*, tenant_id: UUID) -> bool:
        if not bool(getattr(settings, "LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED", False)):
            return False
        if is_production_env():
            return False
        if str(getattr(settings, "AUTH_MODE", "jwt") or "jwt").strip().lower() != "header":
            return False
        default_tenant_id = DatasetService._default_tenant_id()
        if default_tenant_id is None or tenant_id != default_tenant_id:
            return False

        request_state = get_request_state()
        if request_state is None:
            return False
        if str(getattr(request_state, "tenant_id_source", "") or "").strip().lower() != "default":
            return False
        return DatasetService._is_loopback_client(getattr(request_state, "client_host", None))

    @staticmethod
    def ensure_member(db: Session, tenant_id: UUID, account_id: str) -> TenantMember:
        member = (
            db.query(TenantMember)
            .filter(TenantMember.tenant_id == tenant_id, TenantMember.user_id == account_id)
            .first()
        )
        if not member:
            if DatasetService._allow_local_owner_bootstrap(tenant_id=tenant_id):
                # Local convenience only: implicit default-tenant bootstrap from loopback header-auth flows.
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
                    is_active=True,
                    is_current=True,
                )
                db.add(member)
                db.commit()
                db.refresh(member)
                return member
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a tenant member")
        if not bool(getattr(member, "is_active", True)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a tenant member")
        return member

    @staticmethod
    def _assert_edit_role(member: TenantMember):
        role = (member.role or "").lower()
        if role not in EDIT_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission to manage dataset")

    @staticmethod
    def get_dataset(db: Session, tenant_id: UUID, dataset_id: UUID) -> Dataset:
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.tenant_id == tenant_id).first()
        if not dataset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
        return dataset

    @staticmethod
    def create_dataset(
        db: Session,
        tenant_id: UUID,
        name: str,
        description: str | None,
        permission: DatasetPermissionEnum,
        owner_id: str,
        partial_members: list[str] | None = None,
        partial_groups: list[UUID] | None = None,
        dataset_metadata: dict | None = None,
    ) -> Dataset:
        member = DatasetService.ensure_member(db, tenant_id, owner_id)
        DatasetService._assert_edit_role(member)
        try:
            if permission != DatasetPermissionEnum.PARTIAL_MEMBERS:
                partial_members = []
                partial_groups = []

            exists = db.query(Dataset.id).filter(Dataset.tenant_id == tenant_id, Dataset.name == name).first()
            if exists:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dataset name already exists")

            dataset = Dataset(
                tenant_id=tenant_id,
                name=name,
                description=description,
                permission=permission,
                owner_id=owner_id,
                dataset_metadata=dict(dataset_metadata or {}),
            )
            db.add(dataset)
            db.flush()

            if permission == DatasetPermissionEnum.PARTIAL_MEMBERS and partial_members:
                DatasetPermissionService.update_partial_member_list(db, tenant_id, dataset.id, partial_members)
            if permission == DatasetPermissionEnum.PARTIAL_MEMBERS and partial_groups:
                DatasetGroupPermissionService.update_partial_group_list(
                    db,
                    tenant_id,
                    dataset.id,
                    partial_groups,
                    actor_id=owner_id,
                )

            db.commit()
            db.refresh(dataset)
            return dataset
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def _validate_dataset_name_update(db: Session, dataset: Dataset, name: str | None) -> None:
        if name is None or name == dataset.name:
            return
        exists = (
            db.query(Dataset.id)
            .filter(Dataset.tenant_id == dataset.tenant_id, Dataset.name == name, Dataset.id != dataset.id)
            .first()
        )
        if exists:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dataset name already exists")

    @staticmethod
    def _apply_dataset_updates(
        dataset: Dataset,
        *,
        name: str | None,
        description: str | None,
        permission: DatasetPermissionEnum | None,
        dataset_metadata: dict | None,
    ) -> None:
        if name is not None and name != dataset.name:
            dataset.name = name
        if description is not None:
            dataset.description = description
        if permission is not None:
            dataset.permission = permission
        if dataset_metadata is not None:
            dataset.dataset_metadata = dict(dataset_metadata)

    @staticmethod
    def _sync_partial_member_permissions(
        db: Session,
        *,
        tenant_id: UUID,
        dataset_id: UUID,
        actor_id: str,
        partial_members: list[str] | None,
        partial_groups: list[UUID] | None,
    ) -> None:
        DatasetPermissionService.update_partial_member_list(db, tenant_id, dataset_id, partial_members or [])
        DatasetGroupPermissionService.update_partial_group_list(
            db,
            tenant_id,
            dataset_id,
            partial_groups or [],
            actor_id=actor_id,
        )

    @staticmethod
    def _sync_dataset_permission_updates(
        db: Session,
        *,
        dataset: Dataset,
        updater_id: str,
        permission: DatasetPermissionEnum | None,
        partial_members: list[str] | None,
        partial_groups: list[UUID] | None,
    ) -> None:
        if permission is not None:
            if permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
                DatasetService._sync_partial_member_permissions(
                    db,
                    tenant_id=dataset.tenant_id,
                    dataset_id=dataset.id,
                    actor_id=updater_id,
                    partial_members=partial_members,
                    partial_groups=partial_groups,
                )
                return
            DatasetPermissionService.clear_partial_member_list(db, dataset.tenant_id, dataset.id)
            DatasetGroupPermissionService.clear_partial_group_list(
                db,
                dataset.tenant_id,
                dataset.id,
                actor_id=updater_id,
            )
            return

        if dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS and partial_members is not None:
            DatasetPermissionService.update_partial_member_list(db, dataset.tenant_id, dataset.id, partial_members)
        if dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS and partial_groups is not None:
            DatasetGroupPermissionService.update_partial_group_list(
                db,
                dataset.tenant_id,
                dataset.id,
                partial_groups,
                actor_id=updater_id,
            )

    @staticmethod
    def update_dataset(
        db: Session,
        dataset: Dataset,
        updater_id: str,
        name: str | None,
        description: str | None,
        permission: DatasetPermissionEnum | None,
        partial_members: list[str] | None,
        partial_groups: list[UUID] | None,
        dataset_metadata: dict | None = None,
    ) -> Dataset:
        member = DatasetService.ensure_member(db, dataset.tenant_id, updater_id)
        DatasetService._assert_edit_role(member)
        try:
            DatasetService._validate_dataset_name_update(db, dataset, name)
            DatasetService._apply_dataset_updates(
                dataset,
                name=name,
                description=description,
                permission=permission,
                dataset_metadata=dataset_metadata,
            )
            DatasetService._sync_dataset_permission_updates(
                db,
                dataset=dataset,
                updater_id=updater_id,
                permission=permission,
                partial_members=partial_members,
                partial_groups=partial_groups,
            )

            db.commit()
            db.refresh(dataset)
            return dataset
        except Exception:
            db.rollback()
            raise

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
        exists = (
            db.query(DatasetPermission)
            .filter(
                DatasetPermission.dataset_id == dataset.id,
                DatasetPermission.tenant_id == dataset.tenant_id,
                DatasetPermission.account_id == account_id,
            )
            .first()
        )
        if exists:
            return True

        # Group-based allowlist (enterprise): allow when any of the account's tenant groups
        # is granted access to the dataset.
        group_ids = list(
            TenantGroupService.resolve_account_group_ids(
                db,
                tenant_id=dataset.tenant_id,
                account_id=account_id,
            )
        )
        if not group_ids:
            observe_group_permission_check(resource="dataset", action="read", result="deny_no_groups")
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
        if group_perm:
            observe_group_permission_check(resource="dataset", action="read", result="allow")
            return True
        observe_group_permission_check(resource="dataset", action="read", result="deny_no_match")
        return False

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
            exists = (
                db.query(DatasetPermission)
                .filter(
                    DatasetPermission.dataset_id == dataset.id,
                    DatasetPermission.tenant_id == dataset.tenant_id,
                    DatasetPermission.account_id == account_id,
                )
                .first()
            )
            if exists:
                return

            group_ids = list(
                TenantGroupService.resolve_account_group_ids(
                    db,
                    tenant_id=dataset.tenant_id,
                    account_id=account_id,
                )
            )
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
                    observe_group_permission_check(resource="dataset", action="write", result="allow")
                    return
                observe_group_permission_check(resource="dataset", action="write", result="deny_no_match")
            else:
                observe_group_permission_check(resource="dataset", action="write", result="deny_no_groups")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No dataset write permission")


class DatasetPermissionService:
    @staticmethod
    def get_dataset_partial_member_list(db: Session, tenant_id: UUID, dataset_id: UUID) -> list[str]:
        rows = (
            db.query(DatasetPermission)
            .filter(DatasetPermission.tenant_id == tenant_id, DatasetPermission.dataset_id == dataset_id)
            .all()
        )
        return [row.account_id for row in rows]

    @staticmethod
    def update_partial_member_list(
        db: Session,
        tenant_id: UUID,
        dataset_id: UUID,
        member_ids: list[str],
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

    @staticmethod
    def clear_partial_member_list(db: Session, tenant_id: UUID, dataset_id: UUID):
        db.query(DatasetPermission).filter(
            DatasetPermission.tenant_id == tenant_id, DatasetPermission.dataset_id == dataset_id
        ).delete()


class DatasetGroupPermissionService:
    @staticmethod
    def get_dataset_partial_group_list(db: Session, tenant_id: UUID, dataset_id: UUID) -> list[UUID]:
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
        group_ids: list[UUID],
        *,
        actor_id: str | None = None,
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

        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="dataset.access.groups.update",
            resource_type="dataset",
            resource_id=str(dataset_id),
            details={
                "requested_count": int(len(group_ids or [])),
                "group_count": int(len(normalized or [])),
            },
        )

    @staticmethod
    def clear_partial_group_list(
        db: Session,
        tenant_id: UUID,
        dataset_id: UUID,
        *,
        actor_id: str | None = None,
    ) -> None:
        db.query(DatasetGroupPermission).filter(
            DatasetGroupPermission.tenant_id == tenant_id,
            DatasetGroupPermission.dataset_id == dataset_id,
        ).delete(synchronize_session=False)
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="dataset.access.groups.update",
            resource_type="dataset",
            resource_id=str(dataset_id),
            details={
                "requested_count": 0,
                "group_count": 0,
                "cleared": True,
            },
        )
