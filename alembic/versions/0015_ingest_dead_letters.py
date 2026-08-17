"""Add ingest dead letters and structured document failure fields."""

from alembic import op

revision = "0015_ingest_dead_letters"
down_revision = "0014_conv_title_source"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS failed_stage VARCHAR(50)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS error_code VARCHAR(100)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_attempts INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ",
    """
    CREATE TABLE IF NOT EXISTS ingest_dead_letters (
        id UUID PRIMARY KEY,
        tenant_id UUID NOT NULL,
        dataset_id UUID NULL,
        document_id UUID NULL REFERENCES documents(id) ON DELETE SET NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'open',
        failed_stage VARCHAR(50) NOT NULL DEFAULT 'unknown',
        error_code VARCHAR(100) NOT NULL DEFAULT 'ingest_failed',
        error_message TEXT NULL,
        source_ref VARCHAR(1000) NULL,
        original_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        retry_count INTEGER NOT NULL DEFAULT 0,
        producer_service VARCHAR(80) NOT NULL DEFAULT 'document_processor',
        schema_version VARCHAR(40) NOT NULL DEFAULT 'mimirq.ingest_dead_letter.v1',
        first_failed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        replayed_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_ingest_dead_letters_tenant_id ON ingest_dead_letters (tenant_id)",
    "CREATE INDEX IF NOT EXISTS ix_ingest_dead_letters_dataset_id ON ingest_dead_letters (dataset_id)",
    "CREATE INDEX IF NOT EXISTS ix_ingest_dead_letters_document_id ON ingest_dead_letters (document_id)",
    "CREATE INDEX IF NOT EXISTS ix_ingest_dead_letters_tenant_status ON ingest_dead_letters (tenant_id, status)",
    (
        "CREATE INDEX IF NOT EXISTS ix_ingest_dead_letters_tenant_document_status "
        "ON ingest_dead_letters (tenant_id, document_id, status)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_ingest_dead_letters_tenant_error_code "
        "ON ingest_dead_letters (tenant_id, error_code)"
    ),
]


DOWNGRADE_SQL = [
    "DROP TABLE IF EXISTS ingest_dead_letters",
    "ALTER TABLE documents DROP COLUMN IF EXISTS next_retry_at",
    "ALTER TABLE documents DROP COLUMN IF EXISTS processing_attempts",
    "ALTER TABLE documents DROP COLUMN IF EXISTS error_code",
    "ALTER TABLE documents DROP COLUMN IF EXISTS failed_stage",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)
