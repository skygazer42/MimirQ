"""Persist versioned ontology action workflows and their step ownership."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0034_ontology_action_workflows"
down_revision = "0033_chunk_lexical_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enterprise_ontology_workflow_requests",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "version_id", sa.Uuid(), sa.ForeignKey("enterprise_ontology_versions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("workflow_id", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("steps", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("canceled_at", sa.DateTime(timezone=True)),
    )
    op.add_column("enterprise_ontology_action_requests", sa.Column("workflow_request_id", sa.Uuid()))


def downgrade() -> None:
    op.drop_column("enterprise_ontology_action_requests", "workflow_request_id")
    op.drop_table("enterprise_ontology_workflow_requests")
