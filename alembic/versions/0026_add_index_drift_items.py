"""Add index drift item tracking table."""

import sqlalchemy as sa

from alembic import op

revision = "0026_add_index_drift_items"
down_revision = "0025_scan_run_active_uniqueness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "index_drift_items",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chunk_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("strictness", sa.String(20), nullable=False, server_default=sa.text("'off'")),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'open'")),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("marker", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("reconcile_task_id", sa.String(255), nullable=True),
        sa.Column("replay_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.func.now(),
        ),
        sa.Column("last_replayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(255), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
    )
    op.create_index("ix_index_drift_items_tenant_id", "index_drift_items", ["tenant_id"])
    op.create_index("ix_index_drift_items_dataset_id", "index_drift_items", ["dataset_id"])
    op.create_index("ix_index_drift_items_document_id", "index_drift_items", ["document_id"])
    op.create_index("ix_index_drift_items_chunk_id", "index_drift_items", ["chunk_id"])
    op.create_index("ix_index_drift_items_operation", "index_drift_items", ["operation"])
    op.create_index("ix_index_drift_items_channel", "index_drift_items", ["channel"])
    op.create_index("ix_index_drift_items_status", "index_drift_items", ["status"])


def downgrade() -> None:
    op.drop_index("ix_index_drift_items_status", table_name="index_drift_items")
    op.drop_index("ix_index_drift_items_channel", table_name="index_drift_items")
    op.drop_index("ix_index_drift_items_operation", table_name="index_drift_items")
    op.drop_index("ix_index_drift_items_chunk_id", table_name="index_drift_items")
    op.drop_index("ix_index_drift_items_document_id", table_name="index_drift_items")
    op.drop_index("ix_index_drift_items_dataset_id", table_name="index_drift_items")
    op.drop_index("ix_index_drift_items_tenant_id", table_name="index_drift_items")
    op.drop_table("index_drift_items")
