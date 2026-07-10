"""Wave26: RAG config templates (experiment management + rollout/rollback).

Adds:
- rag_config_templates: versioned retrieval/rerank config patches with A/B routing fields.
"""


from alembic import op

revision = "0013_rag_config_templates"
down_revision = "0012_scim_provisioning_hardening"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    # Core table (tenant-scoped; versioned; optional A/B routing).
    "CREATE TABLE IF NOT EXISTS rag_config_templates (\n"
    "\tid UUID NOT NULL,\n"
    "\ttenant_id UUID NOT NULL,\n"
    "\tname VARCHAR(200) NOT NULL,\n"
    "\tdescription TEXT,\n"
    "\tconfig_patch JSONB NOT NULL DEFAULT '{}'::jsonb,\n"
    "\tis_active BOOLEAN NOT NULL DEFAULT true,\n"
    "\tusage_count INTEGER NOT NULL DEFAULT 0,\n"
    "\ttemplate_key VARCHAR(100),\n"
    "\tversion INTEGER NOT NULL DEFAULT 1,\n"
    "\tparent_id UUID,\n"
    "\tab_experiment_key VARCHAR(100),\n"
    "\tab_variant VARCHAR(50),\n"
    "\tab_weight FLOAT NOT NULL DEFAULT 1.0,\n"
    "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),\n"
    "\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),\n"
    "\tPRIMARY KEY (id)\n"
    ")",
    # Indexes (mirror PromptTemplate patterns).
    "CREATE INDEX IF NOT EXISTS ix_rag_config_templates_tenant_id ON rag_config_templates (tenant_id)",
    "CREATE INDEX IF NOT EXISTS ix_rag_config_templates_template_key ON rag_config_templates (template_key)",
    "CREATE INDEX IF NOT EXISTS ix_rag_config_templates_ab_experiment_key ON rag_config_templates (ab_experiment_key)",
    "CREATE INDEX IF NOT EXISTS ix_rag_config_templates_tenant_name ON rag_config_templates (tenant_id, name)",
    "CREATE INDEX IF NOT EXISTS ix_rag_config_templates_tenant_active ON rag_config_templates (tenant_id, is_active)",
    "CREATE INDEX IF NOT EXISTS ix_rag_config_templates_tenant_template_key_version\n"
    "\tON rag_config_templates (tenant_id, template_key, version)",
    "CREATE INDEX IF NOT EXISTS ix_rag_config_templates_tenant_ab_experiment\n"
    "\tON rag_config_templates (tenant_id, ab_experiment_key)",
]


DOWNGRADE_SQL = [
    "DROP TABLE IF EXISTS rag_config_templates;",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)

