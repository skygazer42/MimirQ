"""Wave23: Document publication status (draft/published/deprecated).

Adds:
- documents.publication_status (NOT NULL, default 'published')
- index for common retrieval filters (tenant/dataset + publication_status)
"""


from alembic import op

revision = "0009_add_document_publication_status"
down_revision = "0008_add_document_lifecycle_fields"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS publication_status VARCHAR(20);",
    "UPDATE documents SET publication_status = 'published' WHERE publication_status IS NULL;",
    "ALTER TABLE documents ALTER COLUMN publication_status SET DEFAULT 'published';",
    "ALTER TABLE documents ALTER COLUMN publication_status SET NOT NULL;",
    "CREATE INDEX IF NOT EXISTS ix_documents_tenant_dataset_publication_status "
    "ON documents (tenant_id, dataset_id, publication_status);",
]


DOWNGRADE_SQL = [
    "DROP INDEX IF EXISTS ix_documents_tenant_dataset_publication_status;",
    "ALTER TABLE documents DROP COLUMN IF EXISTS publication_status;",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)

