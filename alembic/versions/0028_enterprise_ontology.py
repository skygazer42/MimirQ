"""Add tenant-owned ontology definitions and immutable release snapshots."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0028_enterprise_ontology"
down_revision = "0027_add_document_index_channels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_document = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "enterprise_ontologies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("draft", json_document, nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_enterprise_ontology_tenant_code"),
    )
    op.create_table(
        "enterprise_ontology_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("ontology_id", sa.Uuid(), sa.ForeignKey("enterprise_ontologies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("definition", json_document, nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("ontology_id", "number", name="uq_enterprise_ontology_version_number"),
        sa.UniqueConstraint("ontology_id", "draft_revision", name="uq_enterprise_ontology_version_draft"),
    )


def downgrade() -> None:
    op.drop_table("enterprise_ontology_versions")
    op.drop_table("enterprise_ontologies")
