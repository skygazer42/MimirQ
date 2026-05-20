"""Repair KG source-event pipeline hash column drift.

Some long-lived local or demo databases can be stamped at the latest Alembic
revision while still missing `kg_source_events.pipeline_hash`. The application
model and KG API already rely on this column for pipeline-scoped graph queries,
so this repair migration is intentionally idempotent.
"""

from __future__ import annotations

from alembic import op

revision = "0016_kg_event_ph_repair"
down_revision = "0015_ingest_dead_letters"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    "ALTER TABLE kg_source_events ADD COLUMN IF NOT EXISTS pipeline_hash VARCHAR(200)",
    "CREATE INDEX IF NOT EXISTS ix_kg_source_events_pipeline_hash ON kg_source_events (pipeline_hash)",
    """
    UPDATE kg_source_events ev
    SET pipeline_hash = COALESCE(d.metadata->>'active_pipeline_hash', d.metadata->>'pipeline_hash')
    FROM documents d
    WHERE ev.document_id = d.id
      AND (ev.pipeline_hash IS NULL OR ev.pipeline_hash = '')
      AND COALESCE(d.metadata->>'active_pipeline_hash', d.metadata->>'pipeline_hash') IS NOT NULL
    """,
    "ALTER TABLE kg_relations ADD COLUMN IF NOT EXISTS pipeline_hash VARCHAR(200)",
    "CREATE INDEX IF NOT EXISTS ix_kg_relations_pipeline_hash ON kg_relations (pipeline_hash)",
    """
    UPDATE kg_relations r
    SET pipeline_hash = COALESCE(d.metadata->>'active_pipeline_hash', d.metadata->>'pipeline_hash')
    FROM documents d
    WHERE r.document_id = d.id
      AND (r.pipeline_hash IS NULL OR r.pipeline_hash = '')
      AND COALESCE(d.metadata->>'active_pipeline_hash', d.metadata->>'pipeline_hash') IS NOT NULL
    """,
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    # No-op by design: this migration repairs schema drift for a column owned by
    # 0005_add_kg_pipeline_hash. Dropping it here could break databases where
    # 0005 already created the column correctly.
    return None
