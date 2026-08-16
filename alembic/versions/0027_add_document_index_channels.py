"""Add document index channel state table."""

import sqlalchemy as sa

from alembic import op

revision = "0027_add_document_index_channels"
down_revision = "0026_add_index_drift_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_index_channels",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_hash", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "pipeline_hash",
            "channel",
            name="uq_document_index_channels_identity",
        ),
    )
    op.create_index("ix_document_index_channels_tenant_id", "document_index_channels", ["tenant_id"])
    op.create_index("ix_document_index_channels_dataset_id", "document_index_channels", ["dataset_id"])
    op.create_index("ix_document_index_channels_document_id", "document_index_channels", ["document_id"])
    op.create_index("ix_document_index_channels_status", "document_index_channels", ["status"])
    op.create_index(
        "ix_document_index_channels_tenant_document",
        "document_index_channels",
        ["tenant_id", "document_id"],
    )
    op.create_index(
        "ix_document_index_channels_tenant_dataset",
        "document_index_channels",
        ["tenant_id", "dataset_id"],
    )
    op.create_index(
        "ix_document_index_channels_tenant_status",
        "document_index_channels",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_index_channels_tenant_status", table_name="document_index_channels")
    op.drop_index("ix_document_index_channels_tenant_dataset", table_name="document_index_channels")
    op.drop_index("ix_document_index_channels_tenant_document", table_name="document_index_channels")
    op.drop_index("ix_document_index_channels_status", table_name="document_index_channels")
    op.drop_index("ix_document_index_channels_document_id", table_name="document_index_channels")
    op.drop_index("ix_document_index_channels_dataset_id", table_name="document_index_channels")
    op.drop_index("ix_document_index_channels_tenant_id", table_name="document_index_channels")
    op.drop_table("document_index_channels")
