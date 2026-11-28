"""Index scoped chunk reads and PostgreSQL lexical fallback in migrated databases."""

from alembic import op
from sqlalchemy import text

revision = "0033_chunk_lexical_indexes"
down_revision = "0032_ontology_action_dispatch"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_document_chunks_tenant_document": "(tenant_id, document_id)",
    "ix_document_chunks_content_fts_active": "USING GIN (to_tsvector('simple', content)) WHERE disabled_at IS NULL",
    "ix_document_chunks_content_trgm_active": "USING GIN (content gin_trgm_ops) WHERE disabled_at IS NULL",
}


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        for name, columns in INDEXES.items():
            # PostgreSQL can keep an invalid index after an interrupted concurrent build.
            valid = op.get_bind().scalar(
                text("SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"), {"name": name}
            )
            if valid is False:
                op.drop_index(name, table_name="document_chunks", postgresql_concurrently=True)
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON document_chunks {columns}")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        for name in reversed(INDEXES):
            op.drop_index(name, table_name="document_chunks", if_exists=True, postgresql_concurrently=True)
