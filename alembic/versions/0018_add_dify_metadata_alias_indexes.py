"""Add Dify metadata alias trigram indexes.

The first metadata-anchor index pass covered service names and title-like
fields. Changzhou service retrieval also binds anchors to alias fields such as
`service_aliases`, so `%term%` ILIKE on those JSONB expressions still degraded
to scans. These indexes keep exact-anchor preflight bounded without changing
retrieval behavior.
"""

from __future__ import annotations

from alembic import op

revision = "0018_dify_metadata_alias_idx"
down_revision = "0017_dify_metadata_anchor_idx"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    """
    CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_primary_alias_trgm_active
    ON document_chunks USING GIN (((metadata->>'primary_alias')) gin_trgm_ops)
    WHERE disabled_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_aliases_trgm_active
    ON document_chunks USING GIN (((metadata->>'aliases')) gin_trgm_ops)
    WHERE disabled_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_service_aliases_trgm_active
    ON document_chunks USING GIN (((metadata->>'service_aliases')) gin_trgm_ops)
    WHERE disabled_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_keywords_trgm_active
    ON document_chunks USING GIN (((metadata->>'keywords')) gin_trgm_ops)
    WHERE disabled_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_semantic_keys_trgm_active
    ON document_chunks USING GIN (((metadata->>'semantic_keys')) gin_trgm_ops)
    WHERE disabled_at IS NULL
    """,
]


DOWNGRADE_SQL = [
    "DROP INDEX IF EXISTS ix_document_chunks_metadata_semantic_keys_trgm_active",
    "DROP INDEX IF EXISTS ix_document_chunks_metadata_keywords_trgm_active",
    "DROP INDEX IF EXISTS ix_document_chunks_metadata_service_aliases_trgm_active",
    "DROP INDEX IF EXISTS ix_document_chunks_metadata_aliases_trgm_active",
    "DROP INDEX IF EXISTS ix_document_chunks_metadata_primary_alias_trgm_active",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)
