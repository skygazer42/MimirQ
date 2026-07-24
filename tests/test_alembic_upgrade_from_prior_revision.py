import os
import uuid
from contextlib import closing

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from app.core.config import settings


def _integration_enabled() -> bool:
    return str(os.getenv("MIMIRQ_INTEGRATION_TESTS", "") or "").strip().lower() in {"1", "true", "yes", "y", "on"}


@pytest.mark.skipif(not _integration_enabled(), reason="Integration tests disabled (set MIMIRQ_INTEGRATION_TESTS=1)")
def test_upgrade_from_previous_revision_backfills_conversation_owner_account_id(monkeypatch: pytest.MonkeyPatch) -> None:
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
        command.upgrade(alembic_cfg, "0020_unique_tenant_member")

        engine = create_engine(test_url)
        try:
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
        finally:
            engine.dispose()
    finally:
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        admin_engine.dispose()
