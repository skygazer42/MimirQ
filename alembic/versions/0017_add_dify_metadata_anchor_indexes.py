"""Add Dify metadata-anchor retrieval indexes.

External knowledge retrieval can use plugin-provided generic metadata anchors
such as `question`, `service_name`, title-like fields, and intent arrays. These
indexes keep that platform-level fallback from degrading into JSONB table scans
on larger corpora.
"""


from alembic import op

revision = "0017_dify_metadata_anchor_idx"
down_revision = "0016_kg_event_ph_repair"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    """
    CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_question_trgm_active
    ON document_chunks USING GIN (((metadata->>'question')) gin_trgm_ops)
    WHERE disabled_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_service_name_trgm_active
    ON document_chunks USING GIN (((metadata->>'service_name')) gin_trgm_ops)
    WHERE disabled_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_case_title_trgm_active
    ON document_chunks USING GIN (((metadata->>'case_title')) gin_trgm_ops)
    WHERE disabled_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_source_topic_trgm_active
    ON document_chunks USING GIN (((metadata->>'source_topic')) gin_trgm_ops)
    WHERE disabled_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_title_trgm_active
    ON document_chunks USING GIN (((metadata->>'title')) gin_trgm_ops)
    WHERE disabled_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_jsonb_active
    ON document_chunks USING GIN (metadata jsonb_path_ops)
    WHERE disabled_at IS NULL
    """,
]


DOWNGRADE_SQL = [
    "DROP INDEX IF EXISTS ix_document_chunks_metadata_jsonb_active",
    "DROP INDEX IF EXISTS ix_document_chunks_metadata_title_trgm_active",
    "DROP INDEX IF EXISTS ix_document_chunks_metadata_source_topic_trgm_active",
    "DROP INDEX IF EXISTS ix_document_chunks_metadata_case_title_trgm_active",
    "DROP INDEX IF EXISTS ix_document_chunks_metadata_service_name_trgm_active",
    "DROP INDEX IF EXISTS ix_document_chunks_metadata_question_trgm_active",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)
