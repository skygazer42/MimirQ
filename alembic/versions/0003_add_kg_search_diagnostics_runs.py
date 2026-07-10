"""Add kg_search_diagnostics_runs table for persisting KG diagnostics snapshots.

Notes:
- This is additive and opt-in (persist_run=true on the diagnostics endpoint).
- We store a compact JSON snapshot (params + summary + compact per-case attribution) to support
  diffing metrics over time without persisting full event/entity payloads.
"""


from alembic import op

revision = "0003_add_kg_search_diagnostics_runs"
down_revision = "0002_add_kg_relations"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    "CREATE TABLE kg_search_diagnostics_runs (\n"
    "\tid UUID NOT NULL, \n"
    "\ttenant_id UUID NOT NULL, \n"
    "\taccount_id VARCHAR(255), \n"
    "\tdataset_id UUID NOT NULL, \n"
    "\tstatus VARCHAR(20) NOT NULL DEFAULT 'completed', \n"
    "\tparams JSONB, \n"
    "\tsummary JSONB, \n"
    "\titems JSONB, \n"
    "\terror_message TEXT, \n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n"
    "\tPRIMARY KEY (id)\n"
    ")",
    "CREATE INDEX ix_kg_search_diagnostics_runs_tenant_id ON kg_search_diagnostics_runs (tenant_id)",
    "CREATE INDEX ix_kg_search_diagnostics_runs_account_id ON kg_search_diagnostics_runs (account_id)",
    "CREATE INDEX ix_kg_search_diagnostics_runs_dataset_id ON kg_search_diagnostics_runs (dataset_id)",
]


DOWNGRADE_SQL = [
    "DROP INDEX IF EXISTS ix_kg_search_diagnostics_runs_dataset_id",
    "DROP INDEX IF EXISTS ix_kg_search_diagnostics_runs_account_id",
    "DROP INDEX IF EXISTS ix_kg_search_diagnostics_runs_tenant_id",
    "DROP TABLE kg_search_diagnostics_runs",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)

