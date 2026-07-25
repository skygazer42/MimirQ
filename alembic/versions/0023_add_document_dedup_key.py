"""Move upload dedup from best-effort scans to a database-enforced key."""

from alembic import op

revision = "0023_document_dedup_key"
down_revision = "0022_message_latest_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(255)")
    op.execute(
        "WITH ranked AS ("
        "  SELECT id, "
        "         concat(lower(metadata->>'file_sha256'), ':', metadata->>'pipeline_hash') AS dedup_key, "
        "         row_number() OVER ("
        "           PARTITION BY tenant_id, dataset_id, lower(metadata->>'file_sha256'), metadata->>'pipeline_hash' "
        "           ORDER BY CASE WHEN status = 'failed' THEN 1 ELSE 0 END, "
        "                    updated_at DESC NULLS LAST, created_at DESC NULLS LAST, id DESC"
        "         ) AS rn "
        "  FROM documents "
        "  WHERE archived_at IS NULL "
        "    AND dataset_id IS NOT NULL "
        "    AND COALESCE(NULLIF(lower(metadata->>'file_sha256'), ''), '') <> '' "
        "    AND COALESCE(NULLIF(metadata->>'pipeline_hash', ''), '') <> ''"
        ") "
        "UPDATE documents AS d "
        "SET dedup_key = ranked.dedup_key "
        "FROM ranked "
        "WHERE d.id = ranked.id "
        "  AND ranked.rn = 1 "
        "  AND COALESCE(d.dedup_key, '') = ''"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_tenant_dataset_dedup_key_active "
        "ON documents (tenant_id, dataset_id, dedup_key) "
        "WHERE archived_at IS NULL AND dataset_id IS NOT NULL AND dedup_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_documents_tenant_dataset_dedup_key_active")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS dedup_key")
