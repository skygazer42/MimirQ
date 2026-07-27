"""Enforce one active dataset scan run per dataset."""

from contextlib import nullcontext

import sqlalchemy as sa

from alembic import op

revision = "0025_scan_run_active_uniqueness"
down_revision = "0024_ingestion_run_doc_unique"
branch_labels = None
depends_on = None


def _dedupe_active_scan_runs(table_name: str) -> None:
    op.execute(
        f"""
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY tenant_id, dataset_id
                       ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END,
                                COALESCE(started_at, updated_at, created_at) DESC,
                                created_at DESC,
                                id DESC
                   ) AS position
            FROM {table_name}
            WHERE status IN ('pending', 'running')
        )
        UPDATE {table_name} AS runs
        SET status = 'failed',
            error_message = CASE
                WHEN COALESCE(runs.error_message, '') = '' THEN 'superseded_by_active_scan_uniqueness'
                ELSE runs.error_message
            END,
            finished_at = COALESCE(runs.finished_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE runs.id IN (SELECT id FROM ranked WHERE position > 1)
        """
    )


def upgrade() -> None:
    _dedupe_active_scan_runs("dataset_profile_scan_runs")
    _dedupe_active_scan_runs("dataset_precheck_scan_runs")

    dialect_name = op.get_bind().dialect.name
    index_options = (
        {
            "postgresql_where": sa.text("status IN ('pending', 'running')"),
            "postgresql_concurrently": True,
        }
        if dialect_name == "postgresql"
        else {"sqlite_where": sa.text("status IN ('pending', 'running')")}
    )
    context = op.get_context().autocommit_block() if dialect_name == "postgresql" else nullcontext()
    with context:
        if dialect_name == "postgresql":
            # A failed concurrent build can leave an INVALID index behind. Drop
            # either a partial-success or invalid artifact so retries are safe.
            op.drop_index(
                "uq_dataset_profile_scan_runs_active_dataset",
                table_name="dataset_profile_scan_runs",
                if_exists=True,
                postgresql_concurrently=True,
            )
            op.drop_index(
                "uq_dataset_precheck_scan_runs_active_dataset",
                table_name="dataset_precheck_scan_runs",
                if_exists=True,
                postgresql_concurrently=True,
            )
        op.create_index(
            "uq_dataset_profile_scan_runs_active_dataset",
            "dataset_profile_scan_runs",
            ["tenant_id", "dataset_id"],
            unique=True,
            if_not_exists=dialect_name != "postgresql",
            **index_options,
        )
        op.create_index(
            "uq_dataset_precheck_scan_runs_active_dataset",
            "dataset_precheck_scan_runs",
            ["tenant_id", "dataset_id"],
            unique=True,
            if_not_exists=dialect_name != "postgresql",
            **index_options,
        )


def downgrade() -> None:
    dialect_name = op.get_bind().dialect.name
    drop_options = {"postgresql_concurrently": True} if dialect_name == "postgresql" else {}
    context = op.get_context().autocommit_block() if dialect_name == "postgresql" else nullcontext()
    with context:
        op.drop_index(
            "uq_dataset_precheck_scan_runs_active_dataset",
            table_name="dataset_precheck_scan_runs",
            if_exists=True,
            **drop_options,
        )
        op.drop_index(
            "uq_dataset_profile_scan_runs_active_dataset",
            table_name="dataset_profile_scan_runs",
            if_exists=True,
            **drop_options,
        )
