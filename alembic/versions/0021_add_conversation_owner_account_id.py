"""Add string conversation owner_account_id for account-scoped chat isolation.

Backfill strategy:
- copy legacy UUID `user_id` into `owner_account_id` where possible
- leave NULL rows untouched so runtime can fail closed until explicitly repaired
"""

from alembic import op

revision = "0021_conv_owner_account"
down_revision = "0020_unique_tenant_member"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS owner_account_id VARCHAR(255)",
    "UPDATE conversations SET owner_account_id = user_id::text WHERE owner_account_id IS NULL AND user_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_conversations_tenant_owner_account_id ON conversations (tenant_id, owner_account_id)",
]


DOWNGRADE_SQL = [
    "DROP INDEX IF EXISTS ix_conversations_tenant_owner_account_id",
    "ALTER TABLE conversations DROP COLUMN IF EXISTS owner_account_id",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)
