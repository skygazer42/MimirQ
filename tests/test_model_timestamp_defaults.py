import runpy
from datetime import timedelta
from pathlib import Path

import pytest

from app.models.dataset import Dataset, DatasetPermission
from app.models.dataset_category import DatasetCategory, DatasetCategoryMembership
from app.models.group_permissions import DatasetGroupPermission, DocumentGroupPermission
from app.models.tenant import Tenant, TenantMember
from app.models.tenant_group import TenantGroup, TenantGroupMember


@pytest.mark.parametrize(
    "model",
    [
        Dataset,
        DatasetPermission,
        DatasetCategory,
        DatasetCategoryMembership,
        DatasetGroupPermission,
        DocumentGroupPermission,
        Tenant,
        TenantMember,
        TenantGroup,
        TenantGroupMember,
    ],
)
def test_model_timestamp_defaults_are_utc_aware(model):
    for column_name in ("created_at", "updated_at"):
        if column_name not in model.__table__.c:
            continue
        column = model.__table__.c[column_name]
        generators = [column.default]
        if column.onupdate is not None:
            generators.append(column.onupdate)

        for generator in generators:
            assert generator is not None
            value = generator.arg(None)
            assert value.utcoffset() == timedelta(0)


def test_tenant_membership_is_unique_per_tenant_and_user() -> None:
    constraints = {constraint.name for constraint in TenantMember.__table__.constraints}
    assert "uq_tenant_members_tenant_user" in constraints


def test_tenant_membership_migration_prefers_non_null_active_current_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = runpy.run_path(
        str(Path(__file__).parents[1] / "alembic/versions/0020_unique_tenant_membership.py")
    )
    executed_sql: list[str] = []

    class Operations:
        def execute(self, statement: str) -> None:
            executed_sql.append(statement)

        def create_unique_constraint(self, *_args: object, **_kwargs: object) -> None:
            pass

        def drop_index(self, *_args: object, **_kwargs: object) -> None:
            pass

    monkeypatch.setitem(migration["upgrade"].__globals__, "op", Operations())
    migration["upgrade"]()

    assert "COALESCE(is_active, false) DESC" in executed_sql[0]
    assert "COALESCE(is_current, false) DESC" in executed_sql[0]
