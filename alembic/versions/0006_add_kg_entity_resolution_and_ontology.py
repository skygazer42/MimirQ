"""Wave15: entity resolution tables + predicate ontology.

Adds:
- kg_entity_aliases: canonical entity aliases (human-governed)
- kg_entity_resolution_actions: merge/split/undo audit payloads (reversible ops)
- kg_entity_redirects: from_entity_id -> to_entity_id redirects (stable URLs)
- kg_predicate_ontology: predicate allowlist + metadata (UI-governed)

Notes:
- We intentionally keep these tables independent from pipeline_hash; entity resolution
  is tenant-wide and should remain stable across document re-processing versions.
"""


from alembic import op

revision = "0006_add_kg_entity_resolution_and_ontology"
down_revision = "0005_add_kg_pipeline_hash"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    # === Entity resolution actions (append-only) ===
    "CREATE TABLE kg_entity_resolution_actions (\n"
    "\tid UUID NOT NULL,\n"
    "\ttenant_id UUID NOT NULL,\n"
    "\tactor_id VARCHAR(255),\n"
    "\taction_type VARCHAR(32) NOT NULL,\n"
    "\tstatus VARCHAR(32) NOT NULL DEFAULT 'applied',\n"
    "\tpayload JSONB NOT NULL DEFAULT '{}'::jsonb,\n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),\n"
    "\treversed_at TIMESTAMP WITH TIME ZONE,\n"
    "\treversed_by VARCHAR(255),\n"
    "\tPRIMARY KEY (id)\n"
    ")",
    "CREATE INDEX ix_kg_entity_resolution_actions_tenant_id ON kg_entity_resolution_actions (tenant_id)",
    "CREATE INDEX ix_kg_entity_resolution_actions_action_type ON kg_entity_resolution_actions (action_type)",
    "CREATE INDEX ix_kg_entity_resolution_actions_status ON kg_entity_resolution_actions (status)",
    "CREATE INDEX ix_kg_entity_resolution_actions_created_at ON kg_entity_resolution_actions (created_at)",
    # === Redirects for merged/deprecated entities ===
    "CREATE TABLE kg_entity_redirects (\n"
    "\tfrom_entity_id UUID NOT NULL,\n"
    "\ttenant_id UUID NOT NULL,\n"
    "\tto_entity_id UUID NOT NULL,\n"
    "\taction_id UUID,\n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),\n"
    "\tcreated_by VARCHAR(255),\n"
    "\textra_data JSONB,\n"
    "\tPRIMARY KEY (from_entity_id),\n"
    "\tFOREIGN KEY(from_entity_id) REFERENCES kg_entities (id) ON DELETE CASCADE,\n"
    "\tFOREIGN KEY(to_entity_id) REFERENCES kg_entities (id) ON DELETE CASCADE,\n"
    "\tFOREIGN KEY(action_id) REFERENCES kg_entity_resolution_actions (id) ON DELETE SET NULL\n"
    ")",
    "CREATE INDEX ix_kg_entity_redirects_tenant_id ON kg_entity_redirects (tenant_id)",
    "CREATE INDEX ix_kg_entity_redirects_to_entity_id ON kg_entity_redirects (to_entity_id)",
    "CREATE INDEX ix_kg_entity_redirects_action_id ON kg_entity_redirects (action_id)",
    # === Human-governed aliases ===
    "CREATE TABLE kg_entity_aliases (\n"
    "\tid UUID NOT NULL,\n"
    "\ttenant_id UUID NOT NULL,\n"
    "\tcanonical_entity_id UUID NOT NULL,\n"
    "\talias VARCHAR(500) NOT NULL,\n"
    "\tnormalized_alias VARCHAR(500) NOT NULL,\n"
    "\tcreated_by VARCHAR(255),\n"
    "\textra_data JSONB,\n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),\n"
    "\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),\n"
    "\tPRIMARY KEY (id),\n"
    "\tFOREIGN KEY(canonical_entity_id) REFERENCES kg_entities (id) ON DELETE CASCADE\n"
    ")",
    "CREATE INDEX ix_kg_entity_aliases_tenant_id ON kg_entity_aliases (tenant_id)",
    "CREATE INDEX ix_kg_entity_aliases_canonical_entity_id ON kg_entity_aliases (canonical_entity_id)",
    "CREATE INDEX ix_kg_entity_aliases_tenant_normalized_alias ON kg_entity_aliases (tenant_id, normalized_alias)",
    "CREATE UNIQUE INDEX uq_kg_entity_aliases_tenant_canonical_normalized_alias\n"
    "\tON kg_entity_aliases (tenant_id, canonical_entity_id, normalized_alias)",
    # === Predicate ontology allowlist ===
    "CREATE TABLE kg_predicate_ontology (\n"
    "\tid UUID NOT NULL,\n"
    "\ttenant_id UUID NOT NULL,\n"
    "\tpredicate VARCHAR(200) NOT NULL,\n"
    "\tdisplay_name VARCHAR(200),\n"
    "\tdescription TEXT,\n"
    "\tis_enabled BOOLEAN NOT NULL DEFAULT TRUE,\n"
    "\textra_data JSONB,\n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),\n"
    "\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),\n"
    "\tPRIMARY KEY (id)\n"
    ")",
    "CREATE INDEX ix_kg_predicate_ontology_tenant_id ON kg_predicate_ontology (tenant_id)",
    "CREATE INDEX ix_kg_predicate_ontology_predicate ON kg_predicate_ontology (predicate)",
    "CREATE INDEX ix_kg_predicate_ontology_is_enabled ON kg_predicate_ontology (is_enabled)",
    "CREATE UNIQUE INDEX uq_kg_predicate_ontology_tenant_predicate\n"
    "\tON kg_predicate_ontology (tenant_id, predicate)",
]


DOWNGRADE_SQL = [
    "DROP INDEX IF EXISTS uq_kg_predicate_ontology_tenant_predicate",
    "DROP INDEX IF EXISTS ix_kg_predicate_ontology_is_enabled",
    "DROP INDEX IF EXISTS ix_kg_predicate_ontology_predicate",
    "DROP INDEX IF EXISTS ix_kg_predicate_ontology_tenant_id",
    "DROP TABLE IF EXISTS kg_predicate_ontology",
    "DROP INDEX IF EXISTS uq_kg_entity_aliases_tenant_canonical_normalized_alias",
    "DROP INDEX IF EXISTS ix_kg_entity_aliases_tenant_normalized_alias",
    "DROP INDEX IF EXISTS ix_kg_entity_aliases_canonical_entity_id",
    "DROP INDEX IF EXISTS ix_kg_entity_aliases_tenant_id",
    "DROP TABLE IF EXISTS kg_entity_aliases",
    "DROP INDEX IF EXISTS ix_kg_entity_redirects_action_id",
    "DROP INDEX IF EXISTS ix_kg_entity_redirects_to_entity_id",
    "DROP INDEX IF EXISTS ix_kg_entity_redirects_tenant_id",
    "DROP TABLE IF EXISTS kg_entity_redirects",
    "DROP INDEX IF EXISTS ix_kg_entity_resolution_actions_created_at",
    "DROP INDEX IF EXISTS ix_kg_entity_resolution_actions_status",
    "DROP INDEX IF EXISTS ix_kg_entity_resolution_actions_action_type",
    "DROP INDEX IF EXISTS ix_kg_entity_resolution_actions_tenant_id",
    "DROP TABLE IF EXISTS kg_entity_resolution_actions",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)

