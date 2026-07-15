from datetime import timedelta

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
