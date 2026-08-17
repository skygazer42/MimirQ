"""Wave25: Group-based allowlists for datasets/documents.

Adds:
- dataset_group_permissions
- document_group_permissions
"""

from alembic import op

revision = "0011_add_group_permissions"
down_revision = "0010_add_tenant_groups"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    # Dataset group allowlist (tenant-safe).
    "CREATE TABLE IF NOT EXISTS dataset_group_permissions (\n"
    "\tid UUID NOT NULL,\n"
    "\ttenant_id UUID NOT NULL,\n"
    "\tdataset_id UUID NOT NULL,\n"
    "\tgroup_id UUID NOT NULL,\n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),\n"
    "\tPRIMARY KEY (id),\n"
    "\tCONSTRAINT uq_dataset_group_permission UNIQUE (tenant_id, dataset_id, group_id),\n"
    "\tCONSTRAINT fk_dataset_group_permissions_tenant_dataset FOREIGN KEY(tenant_id, dataset_id)\n"
    "\t\tREFERENCES datasets (tenant_id, id) ON DELETE CASCADE,\n"
    "\tCONSTRAINT fk_dataset_group_permissions_tenant_group FOREIGN KEY(tenant_id, group_id)\n"
    "\t\tREFERENCES tenant_groups (tenant_id, id) ON DELETE CASCADE\n"
    ");",
    "CREATE INDEX IF NOT EXISTS ix_dataset_group_permissions_tenant_id ON dataset_group_permissions (tenant_id);",
    "CREATE INDEX IF NOT EXISTS ix_dataset_group_permissions_tenant_dataset ON dataset_group_permissions (tenant_id, dataset_id);",
    "CREATE INDEX IF NOT EXISTS ix_dataset_group_permissions_tenant_group ON dataset_group_permissions (tenant_id, group_id);",
    # Document group allowlist.
    "CREATE TABLE IF NOT EXISTS document_group_permissions (\n"
    "\tid UUID NOT NULL,\n"
    "\ttenant_id UUID NOT NULL,\n"
    "\tdocument_id UUID NOT NULL,\n"
    "\tgroup_id UUID NOT NULL,\n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),\n"
    "\tPRIMARY KEY (id),\n"
    "\tCONSTRAINT uq_document_group_permission UNIQUE (tenant_id, document_id, group_id),\n"
    "\tCONSTRAINT fk_document_group_permissions_document FOREIGN KEY(document_id)\n"
    "\t\tREFERENCES documents (id) ON DELETE CASCADE,\n"
    "\tCONSTRAINT fk_document_group_permissions_tenant_group FOREIGN KEY(tenant_id, group_id)\n"
    "\t\tREFERENCES tenant_groups (tenant_id, id) ON DELETE CASCADE\n"
    ");",
    "CREATE INDEX IF NOT EXISTS ix_document_group_permissions_tenant_id ON document_group_permissions (tenant_id);",
    "CREATE INDEX IF NOT EXISTS ix_document_group_permissions_tenant_document ON document_group_permissions (tenant_id, document_id);",
    "CREATE INDEX IF NOT EXISTS ix_document_group_permissions_tenant_group ON document_group_permissions (tenant_id, group_id);",
]


DOWNGRADE_SQL = [
    "DROP INDEX IF EXISTS ix_document_group_permissions_tenant_group;",
    "DROP INDEX IF EXISTS ix_document_group_permissions_tenant_document;",
    "DROP INDEX IF EXISTS ix_document_group_permissions_tenant_id;",
    "DROP TABLE IF EXISTS document_group_permissions;",
    "DROP INDEX IF EXISTS ix_dataset_group_permissions_tenant_group;",
    "DROP INDEX IF EXISTS ix_dataset_group_permissions_tenant_dataset;",
    "DROP INDEX IF EXISTS ix_dataset_group_permissions_tenant_id;",
    "DROP TABLE IF EXISTS dataset_group_permissions;",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)
