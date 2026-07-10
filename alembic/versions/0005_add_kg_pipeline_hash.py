"""Add pipeline_hash columns to KG tables.

Motivation:
- KG extraction/search should be pipeline/version-aware (document_versions).
- This adds a nullable `pipeline_hash` column to KG rows so later waves can
  scope queries and drift diagnostics by pipeline version.

Notes:
- Columns are nullable for backwards compatibility; we best-effort backfill from
  documents.metadata (active_pipeline_hash/pipeline_hash) for existing rows.
"""


from alembic import op

revision = "0005_add_kg_pipeline_hash"
down_revision = "0004_add_kg_search_diagnostics_runs_compound_index"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    # kg_source_events
    "ALTER TABLE kg_source_events ADD COLUMN pipeline_hash VARCHAR(200)",
    "CREATE INDEX IF NOT EXISTS ix_kg_source_events_pipeline_hash ON kg_source_events (pipeline_hash)",
    # Backfill from document metadata (best-effort; safe on Postgres).
    "UPDATE kg_source_events ev\n"
    "SET pipeline_hash = COALESCE(d.metadata->>'active_pipeline_hash', d.metadata->>'pipeline_hash')\n"
    "FROM documents d\n"
    "WHERE ev.document_id = d.id AND (ev.pipeline_hash IS NULL OR ev.pipeline_hash = '')",
    # kg_relations
    "ALTER TABLE kg_relations ADD COLUMN pipeline_hash VARCHAR(200)",
    "CREATE INDEX IF NOT EXISTS ix_kg_relations_pipeline_hash ON kg_relations (pipeline_hash)",
    "UPDATE kg_relations r\n"
    "SET pipeline_hash = COALESCE(d.metadata->>'active_pipeline_hash', d.metadata->>'pipeline_hash')\n"
    "FROM documents d\n"
    "WHERE r.document_id = d.id AND (r.pipeline_hash IS NULL OR r.pipeline_hash = '')",
]


DOWNGRADE_SQL = [
    "DROP INDEX IF EXISTS ix_kg_relations_pipeline_hash",
    "ALTER TABLE kg_relations DROP COLUMN pipeline_hash",
    "DROP INDEX IF EXISTS ix_kg_source_events_pipeline_hash",
    "ALTER TABLE kg_source_events DROP COLUMN pipeline_hash",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)

