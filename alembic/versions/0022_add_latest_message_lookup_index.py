"""Add the composite index used by latest-message lookups."""

from alembic import op

revision = "0022_message_latest_idx"
down_revision = "0021_conv_owner_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_tenant_conversation_created_at "
        "ON messages (tenant_id, conversation_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_tenant_conversation_created_at")
