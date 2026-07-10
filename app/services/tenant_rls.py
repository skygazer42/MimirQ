
from typing import Any


def _quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def build_tenant_rls_bundle(
    *,
    tenant_table: str,
    managed_tables: list[str],
    tenant_column: str = "tenant_id",
    role_column: str = "role",
    admin_role: str = "admin",
) -> dict[str, Any]:
    tenant_table_q = _quote_ident(tenant_table)
    tenant_column_q = _quote_ident(tenant_column)
    role_column_q = _quote_ident(role_column)
    admin_role_s = _quote_literal(str(admin_role or "admin").strip() or "admin")

    is_admin_sql = (
        "CREATE OR REPLACE FUNCTION is_admin() RETURNS boolean\n"  # noqa: S608 - identifiers and literals are quoted locally.
        "LANGUAGE sql SECURITY DEFINER AS $$\n"
        "    SELECT EXISTS (\n"
        f"        SELECT 1 FROM {tenant_table_q} WHERE id = auth.uid() AND {role_column_q} = {admin_role_s}\n"
        "    )\n"
        "$$;"
    )

    tenant_matches_sql = (
        "CREATE OR REPLACE FUNCTION tenant_matches(resource_tenant uuid) RETURNS boolean\n"  # noqa: S608 - identifiers are quoted locally.
        "LANGUAGE sql SECURITY DEFINER AS $$\n"
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
        table_q = _quote_ident(table_name)
        read_policy_q = _quote_ident(f"{table_name}_tenant_read")
        write_policy_q = _quote_ident(f"{table_name}_tenant_write")
        policies[table_name] = {
            "enable_rls": f"ALTER TABLE {table_q} ENABLE ROW LEVEL SECURITY;",
            "select_policy": (
                f"CREATE POLICY {read_policy_q} ON {table_q} "
                f"FOR SELECT USING (is_admin() OR tenant_matches({tenant_column_q}));"
            ),
            "write_policy": (
                f"CREATE POLICY {write_policy_q} ON {table_q} "
                f"FOR ALL USING (is_admin() OR tenant_matches({tenant_column_q})) "
                f"WITH CHECK (is_admin() OR tenant_matches({tenant_column_q}));"
            ),
        }

    return {
        "schema": "mimirq.tenant_rls_bundle.v1",
        "functions": {
            "is_admin": is_admin_sql,
            "tenant_matches": tenant_matches_sql,
        },
        "policies": policies,
    }


__all__ = ["build_tenant_rls_bundle"]
