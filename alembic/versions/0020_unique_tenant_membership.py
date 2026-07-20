"""Prevent duplicate tenant memberships."""

from alembic import op

revision = "0020_unique_tenant_member"
down_revision = "0019_feedback_triage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY tenant_id, user_id
                       ORDER BY COALESCE(is_active, false) DESC,
                                COALESCE(is_current, false) DESC,
                                CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END,
                                created_at ASC, id ASC
                   ) AS position
            FROM tenant_members
            WHERE user_id IS NOT NULL
        )
        DELETE FROM tenant_members
        WHERE id IN (SELECT id FROM ranked WHERE position > 1)
        """
    )
    op.create_unique_constraint(
        "uq_tenant_members_tenant_user",
        "tenant_members",
        ["tenant_id", "user_id"],
    )
    op.drop_index("ix_tenant_members_tenant_user_id", table_name="tenant_members")


def downgrade() -> None:
    op.create_index(
        "ix_tenant_members_tenant_user_id",
        "tenant_members",
        ["tenant_id", "user_id"],
        unique=False,
    )
    op.drop_constraint("uq_tenant_members_tenant_user", "tenant_members", type_="unique")
