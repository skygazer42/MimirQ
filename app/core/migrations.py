"""
Database schema migration module.

Uses `Base.metadata.create_all()` at startup, which does not modify existing tables.
To maintain smooth deployments without immediately using Alembic, we apply a set of
safe `ALTER TABLE ... IF NOT EXISTS` operations.

Only runs on PostgreSQL. Failures are ignored to avoid blocking startup.
"""

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

MigrationStatement = str | tuple[str, Mapping[str, object]]


def _default_tenant_uuid() -> str:
    """
    Resolve default tenant UUID for backfilling legacy rows.

    Keep this best-effort and side-effect free: if settings are unavailable or invalid,
    fall back to the well-known all-zero UUID.
    """
    fallback = "00000000-0000-0000-0000-000000000000"
    try:
        from app.core.config import settings

        raw = str(getattr(settings, "DEFAULT_TENANT_ID", "") or "").strip()
        return str(UUID(raw)) if raw else fallback
    except Exception:  # noqa: BLE001
        return fallback


def _tenant_id_migrations(table: str, default_tenant: str) -> list[MigrationStatement]:
    """
    Add tenant_id to legacy tables and ensure it is non-null with a stable default.

    Notes:
    - We avoid assumptions about existing data; single-tenant legacy rows are backfilled
      with DEFAULT_TENANT_ID.
    - Each statement is idempotent and executed best-effort.
    """
    params = {"default_tenant": default_tenant}
    return [
        # Add column for legacy schemas (covers the "column does not exist" crashes).
        (
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id UUID NOT NULL DEFAULT CAST(:default_tenant AS uuid);",  # noqa: S608 - table names are internal static migration targets.
            params,
        ),
        # If the column existed but was nullable, backfill and harden.
        (f"UPDATE {table} SET tenant_id = CAST(:default_tenant AS uuid) WHERE tenant_id IS NULL;", params),  # noqa: S608 - table names are internal static migration targets.
        (f"ALTER TABLE {table} ALTER COLUMN tenant_id SET DEFAULT CAST(:default_tenant AS uuid);", params),  # noqa: S608 - table names are internal static migration targets.
        f"ALTER TABLE {table} ALTER COLUMN tenant_id SET NOT NULL;",  # noqa: S608 - table names are internal static migration targets.
    ]


def apply_runtime_migrations(engine) -> None:
    """Apply small schema changes needed by newer code paths."""
    try:
        if engine.dialect.name != "postgresql":
            return

        default_tenant = _default_tenant_uuid()
        ddl_statements = [
            # =========================
            # Multi-tenant columns (legacy DB compatibility)
            # =========================
            *_tenant_id_migrations("documents", default_tenant),
            *_tenant_id_migrations("document_chunks", default_tenant),
            *_tenant_id_migrations("conversations", default_tenant),
            *_tenant_id_migrations("messages", default_tenant),
            *_tenant_id_migrations("datasets", default_tenant),
            *_tenant_id_migrations("dataset_permissions", default_tenant),
            *_tenant_id_migrations("prompt_templates", default_tenant),
            *_tenant_id_migrations("tenant_members", default_tenant),
            *_tenant_id_migrations("message_feedback", default_tenant),
            *_tenant_id_migrations("ragas_evaluation_runs", default_tenant),
            *_tenant_id_migrations("ragas_evaluation_items", default_tenant),
            *_tenant_id_migrations("ragas_regression_cases", default_tenant),
            *_tenant_id_migrations("ragas_regression_runs", default_tenant),
            *_tenant_id_migrations("ragas_regression_items", default_tenant),

            # =========================
            # RAGAS regression suite: evidence sources (case-level)
            # =========================
            "ALTER TABLE ragas_regression_cases ADD COLUMN IF NOT EXISTS reference_sources JSONB;",
            "UPDATE ragas_regression_cases SET reference_sources = '[]'::jsonb WHERE reference_sources IS NULL;",
            "ALTER TABLE ragas_regression_cases ALTER COLUMN reference_sources SET DEFAULT '[]'::jsonb;",
            "ALTER TABLE ragas_regression_cases ALTER COLUMN reference_sources SET NOT NULL;",

            # =========================
            # EvidenceSuite: import metadata on draft items
            # =========================
            "ALTER TABLE evidence_items ADD COLUMN IF NOT EXISTS tags JSONB;",
            "UPDATE evidence_items SET tags = '[]'::jsonb WHERE tags IS NULL;",
            "ALTER TABLE evidence_items ALTER COLUMN tags SET DEFAULT '[]'::jsonb;",
            "ALTER TABLE evidence_items ALTER COLUMN tags SET NOT NULL;",
            "ALTER TABLE evidence_items ADD COLUMN IF NOT EXISTS source_metadata JSONB;",
            "UPDATE evidence_items SET source_metadata = '{}'::jsonb WHERE source_metadata IS NULL;",
            "ALTER TABLE evidence_items ALTER COLUMN source_metadata SET DEFAULT '{}'::jsonb;",
            "ALTER TABLE evidence_items ALTER COLUMN source_metadata SET NOT NULL;",

            # Dataset-scoped regression runs (for per-dataset health/report).
            "ALTER TABLE ragas_regression_runs ADD COLUMN IF NOT EXISTS dataset_id UUID;",
            "CREATE INDEX IF NOT EXISTS ix_ragas_regression_runs_tenant_dataset_created_at "
            "ON ragas_regression_runs (tenant_id, dataset_id, created_at);",

            # Regression item meta for audit (abstain + context ids).
            "ALTER TABLE ragas_regression_items ADD COLUMN IF NOT EXISTS meta JSONB;",
            "UPDATE ragas_regression_items SET meta = '{}'::jsonb WHERE meta IS NULL;",
            "ALTER TABLE ragas_regression_items ALTER COLUMN meta SET DEFAULT '{}'::jsonb;",

            # Store per-message run metadata (metrics/request_id/route/etc.)
            'ALTER TABLE messages ADD COLUMN IF NOT EXISTS message_metadata JSONB;',

            # =========================
            # Document-level ACL ("security trimming")
            # =========================
            'ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner_id VARCHAR(255);',
            'ALTER TABLE documents ADD COLUMN IF NOT EXISTS access_mode VARCHAR(50);',

            # =========================
            # Ops-T021: Document lifecycle (governance)
            # =========================
            'ALTER TABLE documents ADD COLUMN IF NOT EXISTS lifecycle_owner VARCHAR(255);',
            'ALTER TABLE documents ADD COLUMN IF NOT EXISTS review_due_at TIMESTAMPTZ;',
            'ALTER TABLE documents ADD COLUMN IF NOT EXISTS authority_level INTEGER;',
            'ALTER TABLE documents ADD COLUMN IF NOT EXISTS supersedes_document_id UUID;',
            'CREATE INDEX IF NOT EXISTS ix_documents_tenant_dataset_review_due_at '
            'ON documents (tenant_id, dataset_id, review_due_at);',
            'CREATE INDEX IF NOT EXISTS ix_documents_tenant_supersedes_document_id '
            'ON documents (tenant_id, supersedes_document_id);',

            # Document lifecycle flags (enable/disable/archive).
            'ALTER TABLE documents ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;',
            'ALTER TABLE documents ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMPTZ;',
            'ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMPTZ;',
            'ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;',

            # Ingest failure tracking / dead-letter replay (mirrors Alembic 0015).
            'ALTER TABLE documents ADD COLUMN IF NOT EXISTS failed_stage VARCHAR(50);',
            'ALTER TABLE documents ADD COLUMN IF NOT EXISTS error_code VARCHAR(100);',
            'ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_attempts INTEGER NOT NULL DEFAULT 0;',
            'ALTER TABLE documents ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;',
            """
            CREATE TABLE IF NOT EXISTS ingest_dead_letters (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                dataset_id UUID NULL,
                document_id UUID NULL REFERENCES documents(id) ON DELETE SET NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                failed_stage VARCHAR(50) NOT NULL DEFAULT 'unknown',
                error_code VARCHAR(100) NOT NULL DEFAULT 'ingest_failed',
                error_message TEXT NULL,
                source_ref VARCHAR(1000) NULL,
                original_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                retry_count INTEGER NOT NULL DEFAULT 0,
                producer_service VARCHAR(80) NOT NULL DEFAULT 'document_processor',
                schema_version VARCHAR(40) NOT NULL DEFAULT 'mimirq.ingest_dead_letter.v1',
                first_failed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                replayed_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            );
            """,
            'CREATE INDEX IF NOT EXISTS ix_ingest_dead_letters_tenant_id ON ingest_dead_letters (tenant_id);',
            'CREATE INDEX IF NOT EXISTS ix_ingest_dead_letters_dataset_id ON ingest_dead_letters (dataset_id);',
            'CREATE INDEX IF NOT EXISTS ix_ingest_dead_letters_document_id ON ingest_dead_letters (document_id);',
            'CREATE INDEX IF NOT EXISTS ix_ingest_dead_letters_tenant_status ON ingest_dead_letters (tenant_id, status);',
            'CREATE INDEX IF NOT EXISTS ix_ingest_dead_letters_tenant_document_status '
            'ON ingest_dead_letters (tenant_id, document_id, status);',
            'CREATE INDEX IF NOT EXISTS ix_ingest_dead_letters_tenant_error_code '
            'ON ingest_dead_letters (tenant_id, error_code);',

            # Datasets: store pipeline/governance defaults in metadata
            "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;",

            # Prompt templates: versioning + A/B testing
            'ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS template_key VARCHAR(100);',
            # Common query pattern: tenant + conversation timeline
            'CREATE INDEX IF NOT EXISTS ix_messages_tenant_conversation_created_at '
            'ON messages (tenant_id, conversation_id, created_at);',
            # Retrieval hot paths: document chunks and document status filters
            'CREATE INDEX IF NOT EXISTS ix_document_chunks_tenant_document '
            'ON document_chunks (tenant_id, document_id);',
            'CREATE INDEX IF NOT EXISTS ix_document_chunks_tenant_document_chunk_index '
            'ON document_chunks (tenant_id, document_id, chunk_index);',
            # Document browsing: tenant/dataset timelines and status filters
            'CREATE INDEX IF NOT EXISTS ix_documents_tenant_created_at '
            'ON documents (tenant_id, created_at);',
            'CREATE INDEX IF NOT EXISTS ix_documents_tenant_dataset_created_at '
            'ON documents (tenant_id, dataset_id, created_at);',
            'CREATE INDEX IF NOT EXISTS ix_documents_tenant_dataset_status '
            'ON documents (tenant_id, dataset_id, status);',
            'CREATE INDEX IF NOT EXISTS ix_documents_tenant_status '
            'ON documents (tenant_id, status);',
            'CREATE INDEX IF NOT EXISTS ix_documents_tenant_archived_at '
            'ON documents (tenant_id, archived_at);',
            'CREATE INDEX IF NOT EXISTS ix_documents_tenant_disabled_at '
            'ON documents (tenant_id, disabled_at);',
            # Chunk timelines / maintenance jobs (rebuild/cleanup)
            'CREATE INDEX IF NOT EXISTS ix_document_chunks_tenant_created_at '
            'ON document_chunks (tenant_id, created_at);',
            'CREATE INDEX IF NOT EXISTS ix_document_chunks_tenant_updated_at '
            'ON document_chunks (tenant_id, updated_at);',
            'CREATE INDEX IF NOT EXISTS ix_document_chunks_tenant_disabled_at '
            'ON document_chunks (tenant_id, disabled_at);',

            # =========================
            # Retrieval lexical acceleration (persistent sparse fallback)
            # =========================
            # Best-effort: pg_trgm requires extension privileges on some managed Postgres.
            "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            # Expression indexes match the query shape in `HybridRetriever._search_lexical_db`.
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_content_fts_active "
            "ON document_chunks USING GIN (to_tsvector('simple', content)) "
            "WHERE disabled_at IS NULL;",
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_content_trgm_active "
            "ON document_chunks USING GIN (content gin_trgm_ops) "
            "WHERE disabled_at IS NULL;",
            # Dify external knowledge metadata-anchor fallback.
            # Mirrors Alembic 0017/0018 for deployments that rely on startup guardrails.
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_question_trgm_active "
            "ON document_chunks USING GIN (((metadata->>'question')) gin_trgm_ops) "
            "WHERE disabled_at IS NULL;",
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_service_name_trgm_active "
            "ON document_chunks USING GIN (((metadata->>'service_name')) gin_trgm_ops) "
            "WHERE disabled_at IS NULL;",
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_case_title_trgm_active "
            "ON document_chunks USING GIN (((metadata->>'case_title')) gin_trgm_ops) "
            "WHERE disabled_at IS NULL;",
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_source_topic_trgm_active "
            "ON document_chunks USING GIN (((metadata->>'source_topic')) gin_trgm_ops) "
            "WHERE disabled_at IS NULL;",
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_title_trgm_active "
            "ON document_chunks USING GIN (((metadata->>'title')) gin_trgm_ops) "
            "WHERE disabled_at IS NULL;",
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_primary_alias_trgm_active "
            "ON document_chunks USING GIN (((metadata->>'primary_alias')) gin_trgm_ops) "
            "WHERE disabled_at IS NULL;",
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_aliases_trgm_active "
            "ON document_chunks USING GIN (((metadata->>'aliases')) gin_trgm_ops) "
            "WHERE disabled_at IS NULL;",
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_service_aliases_trgm_active "
            "ON document_chunks USING GIN (((metadata->>'service_aliases')) gin_trgm_ops) "
            "WHERE disabled_at IS NULL;",
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_keywords_trgm_active "
            "ON document_chunks USING GIN (((metadata->>'keywords')) gin_trgm_ops) "
            "WHERE disabled_at IS NULL;",
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_semantic_keys_trgm_active "
            "ON document_chunks USING GIN (((metadata->>'semantic_keys')) gin_trgm_ops) "
            "WHERE disabled_at IS NULL;",
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_metadata_jsonb_active "
            "ON document_chunks USING GIN (metadata jsonb_path_ops) "
            "WHERE disabled_at IS NULL;",
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
            'ALTER TABLE conversations ADD COLUMN IF NOT EXISTS dataset_id UUID;',
            'ALTER TABLE conversations ADD COLUMN IF NOT EXISTS owner_account_id VARCHAR(255);',
            'UPDATE conversations SET owner_account_id = user_id::text '
            'WHERE owner_account_id IS NULL AND user_id IS NOT NULL;',
            'CREATE INDEX IF NOT EXISTS ix_conversations_tenant_updated_at '
            'ON conversations (tenant_id, updated_at);',
            'CREATE INDEX IF NOT EXISTS ix_conversations_tenant_created_at '
            'ON conversations (tenant_id, created_at);',
            'CREATE INDEX IF NOT EXISTS ix_conversations_tenant_dataset_updated_at '
            'ON conversations (tenant_id, dataset_id, updated_at);',
            'CREATE INDEX IF NOT EXISTS ix_conversations_tenant_owner_account_id '
            'ON conversations (tenant_id, owner_account_id);',

            # Datasets / permissions: access control checks
            'CREATE INDEX IF NOT EXISTS ix_datasets_tenant_updated_at '
            'ON datasets (tenant_id, updated_at);',
            'CREATE INDEX IF NOT EXISTS ix_dataset_permissions_tenant_account_id '
            'ON dataset_permissions (tenant_id, account_id);',

            # =========================
            # Task 28: Dataset isolation DB constraints (tenant-safe)
            # =========================
            # Required for composite foreign keys: (tenant_id, dataset_id) -> datasets(tenant_id, id).
            'CREATE UNIQUE INDEX IF NOT EXISTS ix_datasets_tenant_id_id '
            'ON datasets (tenant_id, id);',
            # Keep dataset names unique per tenant for predictable UX and safer references.
            'CREATE UNIQUE INDEX IF NOT EXISTS ix_datasets_tenant_name '
            'ON datasets (tenant_id, name);',

            # Chunk presets: dataset scoping (governance + reproducibility).
            'ALTER TABLE chunk_presets ADD COLUMN IF NOT EXISTS dataset_id UUID;',
            'CREATE INDEX IF NOT EXISTS ix_chunk_presets_tenant_dataset_updated_at '
            'ON chunk_presets (tenant_id, dataset_id, updated_at);',
            'ALTER TABLE chunk_presets '
            'ADD CONSTRAINT fk_chunk_presets_tenant_dataset '
            'FOREIGN KEY (tenant_id, dataset_id) REFERENCES datasets (tenant_id, id);',

            # Composite indexes for common joins/filters.
            'CREATE INDEX IF NOT EXISTS ix_dataset_permissions_tenant_dataset_id '
            'ON dataset_permissions (tenant_id, dataset_id);',

            # Composite FKs (best-effort; may fail on legacy inconsistent data).
            'ALTER TABLE documents '
            'ADD CONSTRAINT fk_documents_tenant_dataset '
            'FOREIGN KEY (tenant_id, dataset_id) REFERENCES datasets (tenant_id, id);',
            'ALTER TABLE dataset_permissions '
            'ADD CONSTRAINT fk_dataset_permissions_tenant_dataset '
            'FOREIGN KEY (tenant_id, dataset_id) REFERENCES datasets (tenant_id, id) ON DELETE CASCADE;',
            'ALTER TABLE connector_configs '
            'ADD CONSTRAINT fk_connector_configs_tenant_dataset '
            'FOREIGN KEY (tenant_id, dataset_id) REFERENCES datasets (tenant_id, id) ON DELETE CASCADE;',
            'ALTER TABLE connector_runs '
            'ADD CONSTRAINT fk_connector_runs_tenant_dataset '
            'FOREIGN KEY (tenant_id, dataset_id) REFERENCES datasets (tenant_id, id) ON DELETE CASCADE;',
            'CREATE INDEX IF NOT EXISTS ix_connector_runs_tenant_dataset_id '
            'ON connector_runs (tenant_id, dataset_id);',
            'ALTER TABLE db_catalog_tables '
            'ADD CONSTRAINT fk_db_catalog_tables_tenant_dataset '
            'FOREIGN KEY (tenant_id, dataset_id) REFERENCES datasets (tenant_id, id) ON DELETE CASCADE;',
            'CREATE INDEX IF NOT EXISTS ix_db_catalog_tables_tenant_dataset_id '
            'ON db_catalog_tables (tenant_id, dataset_id);',
            'ALTER TABLE dataset_profile_scan_runs '
            'ADD CONSTRAINT fk_dataset_profile_scan_runs_tenant_dataset '
            'FOREIGN KEY (tenant_id, dataset_id) REFERENCES datasets (tenant_id, id) ON DELETE CASCADE;',
            'ALTER TABLE dataset_precheck_scan_runs '
            'ADD CONSTRAINT fk_dataset_precheck_scan_runs_tenant_dataset '
            'FOREIGN KEY (tenant_id, dataset_id) REFERENCES datasets (tenant_id, id) ON DELETE CASCADE;',

            # =========================
            # Dataset categories (tree) + memberships
            # =========================
            'CREATE UNIQUE INDEX IF NOT EXISTS ix_dataset_categories_tenant_id_id '
            'ON dataset_categories (tenant_id, id);',
            'ALTER TABLE dataset_categories '
            'ADD CONSTRAINT fk_dataset_categories_tenant_parent '
            'FOREIGN KEY (tenant_id, parent_id) REFERENCES dataset_categories (tenant_id, id) ON DELETE CASCADE;',
            'ALTER TABLE dataset_category_memberships '
            'ADD CONSTRAINT fk_dataset_category_memberships_tenant_dataset '
            'FOREIGN KEY (tenant_id, dataset_id) REFERENCES datasets (tenant_id, id) ON DELETE CASCADE;',
            'ALTER TABLE dataset_category_memberships '
            'ADD CONSTRAINT fk_dataset_category_memberships_tenant_category '
            'FOREIGN KEY (tenant_id, category_id) REFERENCES dataset_categories (tenant_id, id) ON DELETE CASCADE;',
            'CREATE INDEX IF NOT EXISTS ix_dataset_categories_tenant_parent_sort '
            'ON dataset_categories (tenant_id, parent_id, sort_order, created_at);',
            'CREATE INDEX IF NOT EXISTS ix_dataset_categories_tenant_name '
            'ON dataset_categories (tenant_id, name);',
            'CREATE INDEX IF NOT EXISTS ix_dataset_category_memberships_tenant_dataset_id '
            'ON dataset_category_memberships (tenant_id, dataset_id);',
            'CREATE INDEX IF NOT EXISTS ix_dataset_category_memberships_tenant_category_id '
            'ON dataset_category_memberships (tenant_id, category_id);',

            # Document ACL allowlist checks
            'CREATE INDEX IF NOT EXISTS ix_document_permissions_tenant_account_id '
            'ON document_permissions (tenant_id, account_id);',
            'CREATE INDEX IF NOT EXISTS ix_document_permissions_tenant_account_document_id '
            'ON document_permissions (tenant_id, account_id, document_id);',
            'CREATE INDEX IF NOT EXISTS ix_document_permissions_tenant_document_id '
            'ON document_permissions (tenant_id, document_id);',
            'CREATE INDEX IF NOT EXISTS ix_documents_tenant_owner_id '
            'ON documents (tenant_id, owner_id);',
            'CREATE INDEX IF NOT EXISTS ix_documents_tenant_access_mode '
            'ON documents (tenant_id, access_mode);',
            'CREATE INDEX IF NOT EXISTS ix_documents_tenant_file_type '
            'ON documents (tenant_id, file_type);',
            'CREATE INDEX IF NOT EXISTS ix_datasets_tenant_owner_id '
            'ON datasets (tenant_id, owner_id);',
            # Optional: file hashing (upload dedupe / duplicate detection).
            "CREATE INDEX IF NOT EXISTS ix_documents_tenant_dataset_sha "
            "ON documents (tenant_id, dataset_id, ((metadata->>'file_sha256')));",
            "CREATE INDEX IF NOT EXISTS ix_documents_tenant_dataset_sha_ph "
            "ON documents (tenant_id, dataset_id, ((metadata->>'file_sha256')), ((metadata->>'pipeline_hash')));",

            # =========================
            # Document pipeline versioning (best-effort backfill for legacy deployments)
            # =========================
            # Promote existing completed docs to have an explicit active pipeline hash.
            "UPDATE documents "
            "SET metadata = jsonb_set("
            "  jsonb_set(COALESCE(metadata, '{}'::jsonb), '{active_pipeline_hash}', metadata->'pipeline_hash', true),"
            "  '{active_pipeline_ready}', 'true'::jsonb, true"
            ") "
            "WHERE (metadata->>'active_pipeline_hash' IS NULL OR metadata->>'active_pipeline_hash' = '') "
            "  AND (metadata->>'pipeline_hash') IS NOT NULL "
            "  AND status = 'completed';",
            # Backfill doc_pipeline_key for existing chunks so version-aware retrieval can filter safely.
            "UPDATE document_chunks AS c "
            "SET metadata = jsonb_set("
            "  jsonb_set(COALESCE(c.metadata, '{}'::jsonb), '{pipeline_hash}', to_jsonb(COALESCE(c.metadata->>'pipeline_hash', d.metadata->>'pipeline_hash')), true),"
            "  '{doc_pipeline_key}', to_jsonb("
            "    COALESCE("
            "      c.metadata->>'doc_pipeline_key',"
            "      concat(c.document_id::text, ':', COALESCE(c.metadata->>'pipeline_hash', d.metadata->>'pipeline_hash'))"
            "    )"
            "  ), true"
            ") "
            "FROM documents AS d "
            "WHERE c.document_id = d.id "
            "  AND c.tenant_id = d.tenant_id "
            "  AND (c.metadata->>'doc_pipeline_key' IS NULL OR c.metadata->>'doc_pipeline_key' = '') "
            "  AND (COALESCE(c.metadata->>'pipeline_hash', d.metadata->>'pipeline_hash') IS NOT NULL) "
            "  AND (COALESCE(c.metadata->>'pipeline_hash', d.metadata->>'pipeline_hash') <> '');",

            # =========================
            # Connector runs (ingestion framework)
            # =========================
            'CREATE INDEX IF NOT EXISTS ix_connector_runs_tenant_created_at '
            'ON connector_runs (tenant_id, created_at);',
            'CREATE INDEX IF NOT EXISTS ix_connector_runs_tenant_status_created_at '
            'ON connector_runs (tenant_id, status, created_at);',
            'CREATE INDEX IF NOT EXISTS ix_connector_run_documents_tenant_run '
            'ON connector_run_documents (tenant_id, run_id);',
            'CREATE INDEX IF NOT EXISTS ix_connector_run_documents_tenant_document '
            'ON connector_run_documents (tenant_id, document_id);',
            # Saved connector configurations (best-effort; requires connector_configs table).
            'CREATE INDEX IF NOT EXISTS ix_connector_configs_tenant_created_at '
            'ON connector_configs (tenant_id, created_at);',
            'CREATE INDEX IF NOT EXISTS ix_connector_configs_tenant_dataset_created_at '
            'ON connector_configs (tenant_id, dataset_id, created_at);',
            'CREATE INDEX IF NOT EXISTS ix_connector_configs_tenant_connector_created_at '
            'ON connector_configs (tenant_id, connector_id, created_at);',
            'CREATE INDEX IF NOT EXISTS ix_connector_configs_tenant_enabled_schedule '
            'ON connector_configs (tenant_id, enabled, schedule_cron);',

            # KG (optional): lookups by tenant/doc and join table hot paths
            'CREATE INDEX IF NOT EXISTS ix_kg_source_events_tenant_document '
            'ON kg_source_events (tenant_id, document_id);',
            'CREATE INDEX IF NOT EXISTS ix_kg_event_entities_event '
            'ON kg_event_entities (event_id);',
            'CREATE INDEX IF NOT EXISTS ix_kg_event_entities_entity '
            'ON kg_event_entities (entity_id);',

            # Users (auth)
            'CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email);',
            'CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username);',
        ]
        # Important: in PostgreSQL, once a statement errors inside a transaction,
        # the whole transaction is marked as failed until rollback. Since these
        # migrations are intentionally best-effort (we swallow errors), each DDL
        # must run in its own transaction so one failure doesn't block the rest.
        with engine.connect() as conn:
            for ddl in ddl_statements:
                if isinstance(ddl, tuple):
                    statement, params = ddl
                else:
                    statement, params = ddl, {}
                try:
                    with conn.begin():
                        conn.execute(text(statement), params)
                except SQLAlchemyError:
                    # Best-effort migrations should never block startup.
                    continue
    except SQLAlchemyError:
        return
