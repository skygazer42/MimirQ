import json
import os
import uuid
from contextlib import closing, contextmanager

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.core.config import settings


def _integration_enabled() -> bool:
    return str(os.getenv("MIMIRQ_INTEGRATION_TESTS", "") or "").strip().lower() in {"1", "true", "yes", "y", "on"}


@contextmanager
def _postgres_alembic_test_database(monkeypatch: pytest.MonkeyPatch):
    base_url = str(os.getenv("DATABASE_URL", "") or "").strip()
    if not base_url:
        pytest.skip("DATABASE_URL is required for Alembic integration upgrade test")

    parsed = make_url(base_url)
    if not str(parsed.drivername).startswith("postgresql"):
        pytest.skip("Alembic integration upgrade test requires PostgreSQL")

    db_name = f"mimirq_alembic_{uuid.uuid4().hex[:12]}"
    maintenance_url = parsed.set(database="postgres")
    test_url = parsed.set(database=db_name)
    test_url_text = test_url.render_as_string(hide_password=False)

    admin_engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))

        monkeypatch.setenv("DATABASE_URL", test_url_text)
        monkeypatch.setattr(settings, "DATABASE_URL", test_url_text, raising=False)

        alembic_cfg = Config("alembic.ini")
        engine = create_engine(test_url)
        try:
            yield alembic_cfg, engine
        finally:
            engine.dispose()
    finally:
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        admin_engine.dispose()


@pytest.mark.skipif(not _integration_enabled(), reason="Integration tests disabled (set MIMIRQ_INTEGRATION_TESTS=1)")
def test_upgrade_from_previous_revision_backfills_conversation_owner_account_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _postgres_alembic_test_database(monkeypatch) as (alembic_cfg, engine):
        command.upgrade(alembic_cfg, "0020_unique_tenant_member")

        tenant_id = uuid.uuid4()
        conversation_id = uuid.uuid4()
        legacy_user_id = uuid.uuid4()

        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO tenants (id, name) VALUES (:tenant_id, :name)"),
                {"tenant_id": tenant_id, "name": f"alembic-{tenant_id}"},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO conversations (id, tenant_id, user_id, title, message_count)
                    VALUES (:conversation_id, :tenant_id, :legacy_user_id, :title, :message_count)
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "tenant_id": tenant_id,
                    "legacy_user_id": legacy_user_id,
                    "title": "legacy conversation",
                    "message_count": 0,
                },
            )

        command.upgrade(alembic_cfg, "head")

        with closing(engine.connect()) as conn:
            row = conn.execute(
                text("SELECT user_id::text, owner_account_id FROM conversations WHERE id = :conversation_id"),
                {"conversation_id": conversation_id},
            ).one()
            indexes = inspect(conn).get_indexes("conversations")

        assert row.user_id == str(legacy_user_id)
        assert row.owner_account_id == str(legacy_user_id)
        assert any(index["name"] == "ix_conversations_tenant_owner_account_id" for index in indexes)


@pytest.mark.skipif(not _integration_enabled(), reason="Integration tests disabled (set MIMIRQ_INTEGRATION_TESTS=1)")
def test_upgrade_to_0026_creates_index_drift_items(monkeypatch: pytest.MonkeyPatch) -> None:
    with _postgres_alembic_test_database(monkeypatch) as (alembic_cfg, engine):
        command.upgrade(alembic_cfg, "0025_scan_run_active_uniqueness")
        assert "index_drift_items" not in inspect(engine).get_table_names()

        command.upgrade(alembic_cfg, "head")

        tenant_id = uuid.uuid4()
        item_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO index_drift_items (
                        id, tenant_id, operation, channel, strictness, status,
                        reason, details, marker, replay_count
                    )
                    VALUES (
                        :item_id, :tenant_id, 'delete', 'vector', 'warn', 'open',
                        'integration-test', CAST(:details AS json), CAST(:marker AS json), 0
                    )
                    """
                ),
                {
                    "item_id": item_id,
                    "tenant_id": tenant_id,
                    "details": json.dumps({"source": "alembic"}),
                    "marker": json.dumps({"sequence": 1}),
                },
            )

        inspector = inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("index_drift_items")}
        indexes = {index["name"] for index in inspector.get_indexes("index_drift_items")}
        with engine.connect() as conn:
            stored = conn.execute(
                text(
                    "SELECT tenant_id::text, details, marker, created_at, updated_at "
                    "FROM index_drift_items WHERE id = :item_id"
                ),
                {"item_id": item_id},
            ).one()

        assert {
            "id",
            "tenant_id",
            "dataset_id",
            "document_id",
            "chunk_id",
            "operation",
            "channel",
            "strictness",
            "status",
            "reason",
            "details",
            "marker",
            "reconcile_task_id",
            "replay_count",
            "created_at",
            "updated_at",
            "last_replayed_at",
            "resolved_at",
            "resolved_by",
            "resolution_note",
        } <= columns
        assert {
            "ix_index_drift_items_tenant_id",
            "ix_index_drift_items_dataset_id",
            "ix_index_drift_items_document_id",
            "ix_index_drift_items_chunk_id",
            "ix_index_drift_items_operation",
            "ix_index_drift_items_channel",
            "ix_index_drift_items_status",
        } <= indexes
        assert stored.tenant_id == str(tenant_id)
        assert stored.details == {"source": "alembic"}
        assert stored.marker == {"sequence": 1}
        assert stored.created_at is not None
        assert stored.updated_at is not None


@pytest.mark.skipif(not _integration_enabled(), reason="Integration tests disabled (set MIMIRQ_INTEGRATION_TESTS=1)")
def test_upgrade_to_0024_dedupes_ingestion_run_documents_and_repairs_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    with _postgres_alembic_test_database(monkeypatch) as (alembic_cfg, engine):
        command.upgrade(alembic_cfg, "0023_document_dedup_key")

        tenant_id = uuid.uuid4()
        dataset_id = uuid.uuid4()
        run_id = uuid.uuid4()
        duplicate_document_id = uuid.uuid4()
        pending_document_id = uuid.uuid4()
        duplicate_failed_row_id = uuid.uuid4()
        duplicate_completed_row_id = uuid.uuid4()
        pending_row_id = uuid.uuid4()

        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO tenants (id, name) VALUES (:tenant_id, :name)"),
                {"tenant_id": tenant_id, "name": f"alembic-{tenant_id}"},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO datasets (
                        id, tenant_id, name, description, permission, owner_id,
                        metadata, created_at, updated_at
                    )
                    VALUES (
                        :dataset_id, :tenant_id, :name, :description, :permission, :owner_id,
                        CAST(:metadata AS jsonb), now(), now()
                    )
                    """
                ),
                {
                    "dataset_id": dataset_id,
                    "tenant_id": tenant_id,
                    "name": f"dataset-{dataset_id}",
                    "description": "alembic dataset",
                    "permission": "ALL_TEAM_MEMBERS",
                    "owner_id": "acct-1",
                    "metadata": json.dumps({}),
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO documents (
                        id, tenant_id, dataset_id, user_id, filename, file_type, file_size, file_path,
                        owner_id, access_mode, status, processing_progress, current_stage, error_message,
                        chunk_count, total_characters, metadata, created_at, updated_at
                    )
                    VALUES
                        (:duplicate_document_id, :tenant_id, :dataset_id, NULL, 'dup.txt', 'txt', 1, '/tmp/dup.txt',
                         'acct-1', 'private', 'completed', 100, 'completed', NULL,
                         0, 0, CAST(:metadata AS jsonb), now(), now()),
                        (
                         :pending_document_id, :tenant_id, :dataset_id, NULL,
                         'pending.txt', 'txt', 1, '/tmp/pending.txt',
                         'acct-1', 'private', 'pending', 0, 'pending', NULL,
                         0, 0, CAST(:metadata AS jsonb), now(), now()
                        )
                    """
                ),
                {
                    "duplicate_document_id": duplicate_document_id,
                    "pending_document_id": pending_document_id,
                    "tenant_id": tenant_id,
                    "dataset_id": dataset_id,
                    "metadata": json.dumps({}),
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO ingestion_runs (
                        id, tenant_id, dataset_id, kind, requested_by, status, config, stats,
                        error_message, created_at, started_at, finished_at
                    )
                    VALUES (
                        :run_id, :tenant_id, :dataset_id, 'upload', 'acct-1', 'running',
                        CAST(:config AS jsonb), CAST(:stats AS jsonb), NULL, now(), now(), NULL
                    )
                    """
                ),
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "dataset_id": dataset_id,
                    "config": json.dumps({}),
                    "stats": json.dumps(
                        {
                            "v": "1",
                            "total_documents": 3,
                            "status_counts": {"failed": 1, "completed": 1, "pending": 1},
                            "progress": 66,
                        }
                    ),
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO ingestion_run_documents (
                        id, tenant_id, run_id, document_id,
                        source_ref, status, created_at
                    )
                    VALUES
                        (
                         :duplicate_failed_row_id, :tenant_id, :run_id,
                         :duplicate_document_id, 'dup.txt', 'failed', now()
                        ),
                        (
                         :duplicate_completed_row_id, :tenant_id, :run_id,
                         :duplicate_document_id, 'dup.txt', ' Completed ',
                         now() - interval '1 hour'
                        ),
                        (:pending_row_id, :tenant_id, :run_id, :pending_document_id, 'pending.txt', 'pending', now())
                    """
                ),
                {
                    "duplicate_failed_row_id": duplicate_failed_row_id,
                    "duplicate_completed_row_id": duplicate_completed_row_id,
                    "pending_row_id": pending_row_id,
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "duplicate_document_id": duplicate_document_id,
                    "pending_document_id": pending_document_id,
                },
            )

        command.upgrade(alembic_cfg, "0024_ingestion_run_doc_unique")

        with closing(engine.connect()) as conn:
            kept_rows = conn.execute(
                text(
                    """
                    SELECT lower(trim(status)), document_id::text, id::text
                    FROM ingestion_run_documents
                    WHERE tenant_id = :tenant_id AND run_id = :run_id
                    ORDER BY status
                    """
                ),
                {"tenant_id": tenant_id, "run_id": run_id},
            ).all()
            run_stats = conn.execute(
                text("SELECT stats FROM ingestion_runs WHERE id = :run_id"),
                {"run_id": run_id},
            ).scalar_one()

        assert kept_rows == [
            ("completed", str(duplicate_document_id), str(duplicate_completed_row_id)),
            ("pending", str(pending_document_id), str(pending_row_id)),
        ]
        assert run_stats["total_documents"] == 2
        assert run_stats["status_counts"] == {"completed": 1, "pending": 1}
        assert run_stats["progress"] == 50

        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO ingestion_run_documents (
                            id, tenant_id, run_id, document_id,
                            source_ref, status, created_at
                        )
                        VALUES (:row_id, :tenant_id, :run_id, :document_id, 'dup-again.txt', 'completed', now())
                        """
                    ),
                    {
                        "row_id": uuid.uuid4(),
                        "tenant_id": tenant_id,
                        "run_id": run_id,
                        "document_id": duplicate_document_id,
                    },
                )
