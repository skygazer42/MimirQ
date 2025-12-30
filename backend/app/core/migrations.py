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
        ]
        with engine.begin() as conn:
            for ddl in ddl_statements:
                conn.execute(text(ddl))
    except Exception:
        return
