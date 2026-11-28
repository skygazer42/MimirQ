"""Persist frozen ontology actions and their business receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0031_enterprise_ontology_actions"
down_revision = "0030_enterprise_ontology_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    payload = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "enterprise_ontology_action_requests",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "version_id", sa.Uuid(), sa.ForeignKey("enterprise_ontology_versions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("action_id", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("inputs", payload, nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("receipt", payload),
    )


def downgrade() -> None:
    op.drop_table("enterprise_ontology_action_requests")
