"""Wave26: SCIM provisioning hardening.

Adds:
- tenant_members.is_active (soft deprovisioning)
- unique tenant_groups.external_id per tenant (when present)
- index for tenant_members lookups (tenant_id, user_id)
"""


from alembic import op

revision = "0012_scim_provisioning_hardening"
down_revision = "0011_add_group_permissions"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    # Tenant member lifecycle (soft deprovision).
    "ALTER TABLE tenant_members ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true;",
    "UPDATE tenant_members SET is_active = true WHERE is_active IS NULL;",
    "ALTER TABLE tenant_members ALTER COLUMN is_active SET DEFAULT true;",
    "ALTER TABLE tenant_members ALTER COLUMN is_active SET NOT NULL;",
    "CREATE INDEX IF NOT EXISTS ix_tenant_members_tenant_user_id ON tenant_members (tenant_id, user_id);",

    # external_id uniqueness for tenant groups (SCIM/IdP alignment).
    "UPDATE tenant_groups SET external_id = NULL WHERE external_id = '';",
    "DROP INDEX IF EXISTS ix_tenant_groups_tenant_external_id;",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_groups_tenant_external_id\n"
    "\tON tenant_groups (tenant_id, external_id)\n"
    "\tWHERE external_id IS NOT NULL AND external_id <> '';",
]


DOWNGRADE_SQL = [
    "DROP INDEX IF EXISTS uq_tenant_groups_tenant_external_id;",
    "CREATE INDEX IF NOT EXISTS ix_tenant_groups_tenant_external_id ON tenant_groups (tenant_id, external_id);",
    "DROP INDEX IF EXISTS ix_tenant_members_tenant_user_id;",
    "ALTER TABLE tenant_members DROP COLUMN IF EXISTS is_active;",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)

