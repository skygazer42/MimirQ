
from typing import Any


def _quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _quote_qualified_ident(name: str) -> str:
    parts = [part.strip() for part in str(name or "").split(".") if part.strip()]
    if not parts:
        return _quote_ident("")
    return ".".join(_quote_ident(part) for part in parts)


def _qualify_with_default_schema(name: str, *, schema_name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return _quote_ident("")
    if "." in raw:
        return _quote_qualified_ident(raw)
    return f"{_quote_ident(schema_name)}.{_quote_ident(raw)}"


def build_tenant_rls_bundle(
    *,
    tenant_table: str,
    managed_tables: list[str],
    tenant_column: str = "tenant_id",
    role_column: str = "role",
    admin_role: str = "admin",
    schema_name: str = "public",
) -> dict[str, Any]:
    bundle_schema = "mimirq.tenant_rls_bundle.v1"
    effective_schema = str(schema_name or "public").strip() or "public"
    helper_schema_q = _quote_ident(effective_schema)
    tenant_table_q = _qualify_with_default_schema(tenant_table, schema_name=effective_schema)
    tenant_column_q = _quote_ident(tenant_column)
    role_column_q = _quote_ident(role_column)
    admin_role_s = _quote_literal(str(admin_role or "admin").strip() or "admin")
    is_admin_fn_q = f"{helper_schema_q}.{_quote_ident('is_admin')}"
    tenant_matches_fn_q = f"{helper_schema_q}.{_quote_ident('tenant_matches')}"

    is_admin_sql = (
        f"CREATE OR REPLACE FUNCTION {is_admin_fn_q}() RETURNS boolean\n"  # noqa: S608 - identifiers and literals are quoted locally.
        "LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$\n"
        "    SELECT EXISTS (\n"
        f"        SELECT 1 FROM {tenant_table_q} WHERE id = auth.uid() AND {role_column_q} = {admin_role_s}\n"
        "    )\n"
        "$$;"
    )

    tenant_matches_sql = (
        f"CREATE OR REPLACE FUNCTION {tenant_matches_fn_q}(resource_tenant uuid) RETURNS boolean\n"  # noqa: S608 - identifiers are quoted locally.
        "LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$\n"
        "    SELECT EXISTS (\n"
        f"        SELECT 1 FROM {tenant_table_q} WHERE id = auth.uid() AND {tenant_column_q} = resource_tenant\n"
        "    )\n"
        "$$;"
    )

    policies: dict[str, dict[str, str]] = {}
    for table in managed_tables or []:
        table_name = str(table or "").strip()
        if not table_name:
            continue
        table_q = _qualify_with_default_schema(table_name, schema_name=effective_schema)
        read_policy_q = _quote_ident(f"{table_name}_tenant_read")
        write_policy_q = _quote_ident(f"{table_name}_tenant_write")
        policies[table_name] = {
            "enable_rls": f"ALTER TABLE {table_q} ENABLE ROW LEVEL SECURITY;",
            "select_policy": (
                f"CREATE POLICY {read_policy_q} ON {table_q} "
                f"FOR SELECT USING ({is_admin_fn_q}() OR {tenant_matches_fn_q}({tenant_column_q}));"
            ),
            "write_policy": (
                f"CREATE POLICY {write_policy_q} ON {table_q} "
                f"FOR ALL USING ({is_admin_fn_q}() OR {tenant_matches_fn_q}({tenant_column_q})) "
                f"WITH CHECK ({is_admin_fn_q}() OR {tenant_matches_fn_q}({tenant_column_q}));"
            ),
        }

    return {
        "schema": bundle_schema,
        "functions": {
            "is_admin": is_admin_sql,
            "tenant_matches": tenant_matches_sql,
        },
        "policies": policies,
    }


__all__ = ["build_tenant_rls_bundle"]
