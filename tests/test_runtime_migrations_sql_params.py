from app.core.migrations import _tenant_id_migrations


def test_tenant_id_migrations_bind_default_tenant_uuid() -> None:
    tenant_id = "00000000-0000-0000-0000-000000000000"

    statements = _tenant_id_migrations("documents", tenant_id)

    parameterized = [statement for statement in statements if isinstance(statement, tuple)]
    rendered_sql = "\n".join(statement[0] if isinstance(statement, tuple) else statement for statement in statements)

    assert len(parameterized) == 3
    assert ":default_tenant" in rendered_sql
    assert f"'{tenant_id}'" not in rendered_sql
    for _, params in parameterized:
        assert params == {"default_tenant": tenant_id}


def test_dify_metadata_anchor_indexes_are_managed_by_alembic_not_runtime_startup() -> None:
    from pathlib import Path

    runtime_text = Path("app/core/migrations.py").read_text(encoding="utf-8")
    migration_text = Path("alembic/versions/0017_add_dify_metadata_anchor_indexes.py").read_text(encoding="utf-8")

    assert "ix_document_chunks_metadata_question_trgm_active" not in runtime_text
    assert "ix_document_chunks_metadata_service_name_trgm_active" not in runtime_text
    assert "ix_document_chunks_metadata_jsonb_active" not in runtime_text
    assert "ix_document_chunks_metadata_question_trgm_active" in migration_text
    assert "ix_document_chunks_metadata_service_name_trgm_active" in migration_text
    assert "ix_document_chunks_metadata_jsonb_active" in migration_text
    assert "gin_trgm_ops" in migration_text
    assert "jsonb_path_ops" in migration_text
