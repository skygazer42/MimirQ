from __future__ import annotations

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from app.models.connector import ConnectorRun
from app.models.connector_config import ConnectorConfig
from app.models.dataset import Dataset, DatasetPermission
from app.models.dataset_category import DatasetCategory, DatasetCategoryMembership
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun
from app.models.dataset_profile_scan import DatasetProfileScanRun
from app.models.db_catalog import DbCatalogTable
from app.models.document import Document


def _has_unique(table, cols: set[str]) -> bool:
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint) and set(constraint.columns.keys()) == cols:
            return True
    return False


def _has_fk_mapping(table, mapping: set[tuple[str, str]]) -> bool:
    """
    mapping: { (local_col, "remote_table.remote_col"), ... }
    """
    for constraint in table.foreign_key_constraints:
        if not isinstance(constraint, ForeignKeyConstraint):
            continue
        pairs = {(fk.parent.name, f"{fk.column.table.name}.{fk.column.name}") for fk in constraint.elements}
        if pairs == mapping:
            return True
    return False


def test_datasets_has_required_unique_constraints():
    t = Dataset.__table__
    assert _has_unique(t, {"tenant_id", "id"})
    assert _has_unique(t, {"tenant_id", "name"})


def test_dataset_permissions_has_composite_dataset_fk():
    assert _has_fk_mapping(
        DatasetPermission.__table__,
        {("tenant_id", "datasets.tenant_id"), ("dataset_id", "datasets.id")},
    )


def test_connector_configs_has_composite_dataset_fk():
    assert _has_fk_mapping(
        ConnectorConfig.__table__,
        {("tenant_id", "datasets.tenant_id"), ("dataset_id", "datasets.id")},
    )


def test_connector_runs_has_composite_dataset_fk():
    assert _has_fk_mapping(
        ConnectorRun.__table__,
        {("tenant_id", "datasets.tenant_id"), ("dataset_id", "datasets.id")},
    )


def test_db_catalog_tables_has_composite_dataset_fk():
    assert _has_fk_mapping(
        DbCatalogTable.__table__,
        {("tenant_id", "datasets.tenant_id"), ("dataset_id", "datasets.id")},
    )


def test_dataset_profile_scan_runs_has_composite_dataset_fk():
    assert _has_fk_mapping(
        DatasetProfileScanRun.__table__,
        {("tenant_id", "datasets.tenant_id"), ("dataset_id", "datasets.id")},
    )


def test_dataset_precheck_scan_runs_has_composite_dataset_fk():
    assert _has_fk_mapping(
        DatasetPrecheckScanRun.__table__,
        {("tenant_id", "datasets.tenant_id"), ("dataset_id", "datasets.id")},
    )


def test_documents_has_composite_dataset_fk():
    assert _has_fk_mapping(
        Document.__table__,
        {("tenant_id", "datasets.tenant_id"), ("dataset_id", "datasets.id")},
    )


def test_dataset_categories_tenant_safe_parent_fk():
    # Enforce that parent_id always references a category in the same tenant.
    assert _has_fk_mapping(
        DatasetCategory.__table__,
        {("tenant_id", "dataset_categories.tenant_id"), ("parent_id", "dataset_categories.id")},
    )


def test_dataset_category_memberships_tenant_safe_fks():
    t = DatasetCategoryMembership.__table__
    assert _has_fk_mapping(
        t,
        {("tenant_id", "datasets.tenant_id"), ("dataset_id", "datasets.id")},
    )
    assert _has_fk_mapping(
        t,
        {("tenant_id", "dataset_categories.tenant_id"), ("category_id", "dataset_categories.id")},
    )

