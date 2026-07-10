"""Wave25: Tenant groups (directory primitive).

Adds:
- tenant_groups
- tenant_group_members
"""


from alembic import op

revision = "0010_add_tenant_groups"
down_revision = "0009_add_document_publication_status"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    # Groups (tenant-scoped).
    "CREATE TABLE IF NOT EXISTS tenant_groups (\n"
    "\tid UUID NOT NULL,\n"
    "\ttenant_id UUID NOT NULL,\n"
    "\tname VARCHAR(255) NOT NULL,\n"
    "\texternal_id VARCHAR(255),\n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),\n"
    "\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),\n"
    "\tPRIMARY KEY (id),\n"
    "\tCONSTRAINT uq_tenant_groups_tenant_id_id UNIQUE (tenant_id, id),\n"
    "\tCONSTRAINT uq_tenant_groups_tenant_name UNIQUE (tenant_id, name)\n"
    ");",
    "CREATE INDEX IF NOT EXISTS ix_tenant_groups_tenant_id ON tenant_groups (tenant_id);",
    "CREATE INDEX IF NOT EXISTS ix_tenant_groups_tenant_external_id ON tenant_groups (tenant_id, external_id);",

    # Memberships.
    "CREATE TABLE IF NOT EXISTS tenant_group_members (\n"
    "\tid UUID NOT NULL,\n"
    "\ttenant_id UUID NOT NULL,\n"
    "\tgroup_id UUID NOT NULL,\n"
    "\tuser_id VARCHAR(255) NOT NULL,\n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),\n"
    "\tPRIMARY KEY (id),\n"
    "\tCONSTRAINT uq_tenant_group_members_group_user UNIQUE (tenant_id, group_id, user_id),\n"
    "\tCONSTRAINT fk_tenant_group_members_tenant_group FOREIGN KEY(tenant_id, group_id)\n"
    "\t\tREFERENCES tenant_groups (tenant_id, id) ON DELETE CASCADE\n"
    ");",
    "CREATE INDEX IF NOT EXISTS ix_tenant_group_members_tenant_id ON tenant_group_members (tenant_id);",
    "CREATE INDEX IF NOT EXISTS ix_tenant_group_members_tenant_user ON tenant_group_members (tenant_id, user_id);",
    "CREATE INDEX IF NOT EXISTS ix_tenant_group_members_tenant_group ON tenant_group_members (tenant_id, group_id);",
]


DOWNGRADE_SQL = [
    "DROP INDEX IF EXISTS ix_tenant_group_members_tenant_group;",
    "DROP INDEX IF EXISTS ix_tenant_group_members_tenant_user;",
    "DROP INDEX IF EXISTS ix_tenant_group_members_tenant_id;",
    "DROP TABLE IF EXISTS tenant_group_members;",
    "DROP INDEX IF EXISTS ix_tenant_groups_tenant_external_id;",
    "DROP INDEX IF EXISTS ix_tenant_groups_tenant_id;",
    "DROP TABLE IF EXISTS tenant_groups;",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)

