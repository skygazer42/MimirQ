"""Wave23: Document lifecycle fields (ops/governance).

Adds:
- documents.lifecycle_owner (nullable)
- documents.review_due_at (nullable)
- documents.authority_level (nullable)
- documents.supersedes_document_id (nullable)
- indexes for common ops queries (tenant/dataset + review_due, supersedes)
"""


from alembic import op

revision = "0008_add_document_lifecycle_fields"
down_revision = "0007_add_chunk_presets_dataset_id"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS lifecycle_owner VARCHAR(255);",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS review_due_at TIMESTAMPTZ;",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS authority_level INTEGER;",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS supersedes_document_id UUID;",
    "CREATE INDEX IF NOT EXISTS ix_documents_tenant_dataset_review_due_at "
    "ON documents (tenant_id, dataset_id, review_due_at);",
    "CREATE INDEX IF NOT EXISTS ix_documents_tenant_supersedes_document_id "
    "ON documents (tenant_id, supersedes_document_id);",
]


DOWNGRADE_SQL = [
    "DROP INDEX IF EXISTS ix_documents_tenant_supersedes_document_id;",
    "DROP INDEX IF EXISTS ix_documents_tenant_dataset_review_due_at;",
    "ALTER TABLE documents DROP COLUMN IF EXISTS supersedes_document_id;",
    "ALTER TABLE documents DROP COLUMN IF EXISTS authority_level;",
    "ALTER TABLE documents DROP COLUMN IF EXISTS review_due_at;",
    "ALTER TABLE documents DROP COLUMN IF EXISTS lifecycle_owner;",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)

