"""Persist evidence-backed document drafts for reauthorization on reopen."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0030_enterprise_ontology_drafts"
down_revision = "0029_enterprise_ontology_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_document = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "enterprise_ontology_draft_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("enterprise_ontology_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request", json_document, nullable=False),
        sa.Column("answer", json_document, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("enterprise_ontology_draft_documents")
