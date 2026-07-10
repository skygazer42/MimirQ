"""Wave18: dataset-scoped chunk presets (governance).

Adds:
- chunk_presets.dataset_id (nullable)
- index for common UI queries (tenant + dataset + updated_at)
- composite FK to ensure dataset_id belongs to the same tenant
"""


from alembic import op

revision = "0007_add_chunk_presets_dataset_id"
down_revision = "0006_add_kg_entity_resolution_and_ontology"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    "ALTER TABLE chunk_presets ADD COLUMN IF NOT EXISTS dataset_id UUID;",
    "CREATE INDEX IF NOT EXISTS ix_chunk_presets_tenant_dataset_updated_at "
    "ON chunk_presets (tenant_id, dataset_id, updated_at);",
    "ALTER TABLE chunk_presets "
    "ADD CONSTRAINT fk_chunk_presets_tenant_dataset "
    "FOREIGN KEY (tenant_id, dataset_id) REFERENCES datasets (tenant_id, id);",
]


DOWNGRADE_SQL = [
    "ALTER TABLE chunk_presets DROP CONSTRAINT IF EXISTS fk_chunk_presets_tenant_dataset;",
    "DROP INDEX IF EXISTS ix_chunk_presets_tenant_dataset_updated_at;",
    "ALTER TABLE chunk_presets DROP COLUMN IF EXISTS dataset_id;",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)

