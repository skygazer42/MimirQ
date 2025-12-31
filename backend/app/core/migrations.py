"""
数据库模式迁移模块
在启动时使用 `Base.metadata.create_all()`，该方法不会修改现有表。
为了在不立即使用 Alembic 的情况下保持部署顺畅，我们应用一组安全的 `ALTER TABLE ... IF NOT EXISTS` 操作。
仅在 PostgreSQL 上运行。失败会被忽略以避免阻塞启动。
"""

from sqlalchemy import text

def apply_runtime_migrations(engine) -> None:
    """Apply small schema changes needed by newer code paths."""
    try:
        if engine.dialect.name != "postgresql":
            return
        ddl_statements = [
            # Store per-message run metadata (metrics/request_id/route/etc.)
            'ALTER TABLE messages ADD COLUMN IF NOT EXISTS message_metadata JSONB;',
            # Common query pattern: tenant + conversation timeline
            'CREATE INDEX IF NOT EXISTS ix_messages_tenant_conversation_created_at '
            'ON messages (tenant_id, conversation_id, created_at);',
            # Retrieval hot paths: document chunks and document status filters
            'CREATE INDEX IF NOT EXISTS ix_document_chunks_tenant_document '
            'ON document_chunks (tenant_id, document_id);',
            'CREATE INDEX IF NOT EXISTS ix_document_chunks_tenant_document_chunk_index '
            'ON document_chunks (tenant_id, document_id, chunk_index);',
            'CREATE INDEX IF NOT EXISTS ix_documents_tenant_status '
            'ON documents (tenant_id, status);',
            # Prompt templates: versioning + A/B testing
            'ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS template_key VARCHAR(100);',
            'ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;',
            'ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS parent_id UUID;',
            'ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS ab_experiment_key VARCHAR(100);',
            'ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS ab_variant VARCHAR(50);',
            'ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS ab_weight DOUBLE PRECISION DEFAULT 1;',
            'CREATE INDEX IF NOT EXISTS ix_prompt_templates_tenant_template_key '
            'ON prompt_templates (tenant_id, template_key);',
            'CREATE INDEX IF NOT EXISTS ix_prompt_templates_tenant_template_key_version '
            'ON prompt_templates (tenant_id, template_key, version);',
            'CREATE INDEX IF NOT EXISTS ix_prompt_templates_tenant_ab_experiment_key '
            'ON prompt_templates (tenant_id, ab_experiment_key);',

            # Conversations: common tenant timeline queries
            'CREATE INDEX IF NOT EXISTS ix_conversations_tenant_updated_at '
            'ON conversations (tenant_id, updated_at);',
            'CREATE INDEX IF NOT EXISTS ix_conversations_tenant_created_at '
            'ON conversations (tenant_id, created_at);',

            # Datasets / permissions: access control checks
            'CREATE INDEX IF NOT EXISTS ix_datasets_tenant_updated_at '
            'ON datasets (tenant_id, updated_at);',
            'CREATE INDEX IF NOT EXISTS ix_dataset_permissions_tenant_account_id '
            'ON dataset_permissions (tenant_id, account_id);',

            # KG (optional): lookups by tenant/doc and join table hot paths
            'CREATE INDEX IF NOT EXISTS ix_kg_source_events_tenant_document '
            'ON kg_source_events (tenant_id, document_id);',
            'CREATE INDEX IF NOT EXISTS ix_kg_event_entities_event '
            'ON kg_event_entities (event_id);',
            'CREATE INDEX IF NOT EXISTS ix_kg_event_entities_entity '
            'ON kg_event_entities (entity_id);',
        ]
        with engine.begin() as conn:
            for ddl in ddl_statements:
                try:
                    conn.execute(text(ddl))
                except Exception:
                    # Best-effort migrations should never block startup.
                    continue
    except Exception:
        return
