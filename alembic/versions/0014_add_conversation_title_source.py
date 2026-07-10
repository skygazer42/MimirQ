"""Add persistent conversation title source.

Backfills existing conversations as:
- auto: empty title, or title matches the legacy "first user message preview"
- manual: anything else
"""


from alembic import op

revision = "0014_conv_title_source"
down_revision = "0013_rag_config_templates"
branch_labels = None
depends_on = None


UPGRADE_SQL = [
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS title_source VARCHAR(16)",
    """
    WITH first_user AS (
        SELECT DISTINCT ON (m.conversation_id)
            m.conversation_id,
            regexp_replace(trim(coalesce(m.content, '')), '\\s+', ' ', 'g') AS content
        FROM messages AS m
        WHERE m.role = 'user'
        ORDER BY m.conversation_id, m.created_at ASC, m.id ASC
    )
    UPDATE conversations AS c
    SET title_source = CASE
        WHEN trim(coalesce(c.title, '')) = '' THEN 'auto'
        WHEN fu.content IS NOT NULL
            AND c.title = CASE
                WHEN char_length(fu.content) > 50 THEN left(fu.content, 50) || '...'
                ELSE fu.content
            END THEN 'auto'
        ELSE 'manual'
    END
    FROM first_user AS fu
    WHERE c.id = fu.conversation_id
    """,
    "UPDATE conversations SET title_source = 'auto' WHERE title_source IS NULL AND trim(coalesce(title, '')) = ''",
    "UPDATE conversations SET title_source = 'manual' WHERE title_source IS NULL",
    "ALTER TABLE conversations ALTER COLUMN title_source SET DEFAULT 'manual'",
    "ALTER TABLE conversations ALTER COLUMN title_source SET NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_conversations_title_source ON conversations (title_source)",
]


DOWNGRADE_SQL = [
    "DROP INDEX IF EXISTS ix_conversations_title_source",
    "ALTER TABLE conversations DROP COLUMN IF EXISTS title_source",
]


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)
