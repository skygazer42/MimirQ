"""Add composite index for kg_search_diagnostics_runs listing queries.

Motivation:
- The runs listing endpoint filters by (tenant_id, dataset_id) and orders by created_at DESC.
- A composite index improves performance once run volume grows.

Notes:
- This is additive and safe to apply online.
"""


from alembic import op

revision = "0004_add_kg_search_diagnostics_runs_compound_index"
down_revision = "0003_add_kg_search_diagnostics_runs"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    "CREATE INDEX ix_kg_search_diagnostics_runs_tenant_dataset_created_at "
    "ON kg_search_diagnostics_runs (tenant_id, dataset_id, created_at DESC)",
]

DOWNGRADE_SQL = [
    "DROP INDEX IF EXISTS ix_kg_search_diagnostics_runs_tenant_dataset_created_at",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)

