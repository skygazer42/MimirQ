"""Add kg_relations table for entity-entity edges.

Notes:
- This is additive and should be safe for existing deployments.
- Relations are used for triples extraction and SkillNet-like skill edges.
"""


from alembic import op

revision = "0002_add_kg_relations"
down_revision = "0001_baseline_schema"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    "CREATE TABLE kg_relations (\n"
    "\tid UUID NOT NULL, \n"
    "\ttenant_id UUID NOT NULL, \n"
    "\tdocument_id UUID, \n"
    "\tchunk_id UUID, \n"
    "\tevent_id UUID, \n"
    "\tsubject_entity_id UUID NOT NULL, \n"
    "\tpredicate VARCHAR(200) NOT NULL, \n"
    "\tpredicate_raw VARCHAR(200), \n"
    "\tobject_entity_id UUID NOT NULL, \n"
    "\tconfidence NUMERIC(5, 2) NOT NULL DEFAULT 0.50, \n"
    "\tqualifiers JSON, \n"
    '\t"references" JSON, \n'
    "\textra_data JSON, \n"
    "\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n"
    "\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n"
    "\tPRIMARY KEY (id), \n"
    "\tFOREIGN KEY(subject_entity_id) REFERENCES kg_entities (id) ON DELETE CASCADE, \n"
    "\tFOREIGN KEY(object_entity_id) REFERENCES kg_entities (id) ON DELETE CASCADE, \n"
    "\tFOREIGN KEY(event_id) REFERENCES kg_source_events (id) ON DELETE SET NULL\n"
    ")",
    "CREATE INDEX ix_kg_relations_tenant_id ON kg_relations (tenant_id)",
    "CREATE INDEX ix_kg_relations_document_id ON kg_relations (document_id)",
    "CREATE INDEX ix_kg_relations_chunk_id ON kg_relations (chunk_id)",
    "CREATE INDEX ix_kg_relations_event_id ON kg_relations (event_id)",
    "CREATE INDEX ix_kg_relations_subject_entity_id ON kg_relations (subject_entity_id)",
    "CREATE INDEX ix_kg_relations_object_entity_id ON kg_relations (object_entity_id)",
    "CREATE INDEX ix_kg_relations_predicate ON kg_relations (predicate)",
]


DOWNGRADE_SQL = [
    "DROP INDEX IF EXISTS ix_kg_relations_predicate",
    "DROP INDEX IF EXISTS ix_kg_relations_object_entity_id",
    "DROP INDEX IF EXISTS ix_kg_relations_subject_entity_id",
    "DROP INDEX IF EXISTS ix_kg_relations_event_id",
    "DROP INDEX IF EXISTS ix_kg_relations_chunk_id",
    "DROP INDEX IF EXISTS ix_kg_relations_document_id",
    "DROP INDEX IF EXISTS ix_kg_relations_tenant_id",
    "DROP TABLE kg_relations",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)

