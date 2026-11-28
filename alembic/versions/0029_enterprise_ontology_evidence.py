"""Store revision-scoped ontology document evidence and active dataset pointers."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0029_enterprise_ontology_evidence"
down_revision = "0028_enterprise_ontology"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enterprise_ontology_datasets",
        sa.Column("dataset_id", sa.Uuid(), sa.ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("enterprise_ontology_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "enterprise_ontology_documents",
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("enterprise_ontology_versions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("pipeline_hash", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunks", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )
    op.create_index("ix_enterprise_document_dataset", "enterprise_ontology_documents", ["tenant_id", "dataset_id"])


def downgrade() -> None:
    op.drop_table("enterprise_ontology_documents")
    op.drop_table("enterprise_ontology_datasets")
