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
