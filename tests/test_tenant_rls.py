from __future__ import annotations

from app.services.tenant_rls import build_tenant_rls_bundle


def test_build_tenant_rls_bundle_emits_security_definer_functions_and_table_policies() -> None:
    bundle = build_tenant_rls_bundle(
        tenant_table="profiles",
        managed_tables=["chat_sessions", "chat_messages", "feedback"],
        tenant_column="tenant_id",
        role_column="role",
        admin_role="admin",
    )

    assert bundle["schema"] == "mimirq.tenant_rls_bundle.v1"
    functions = bundle["functions"]
    assert "CREATE OR REPLACE FUNCTION is_admin()" in functions["is_admin"]
    assert "SECURITY DEFINER" in functions["is_admin"]
    assert "auth.uid()" in functions["is_admin"]
    assert "CREATE OR REPLACE FUNCTION tenant_matches(resource_tenant uuid)" in functions["tenant_matches"]

    policies = bundle["policies"]
    assert set(policies.keys()) == {"chat_sessions", "chat_messages", "feedback"}
    assert "ENABLE ROW LEVEL SECURITY" in policies["chat_messages"]["enable_rls"]
    assert "USING (is_admin() OR tenant_matches(tenant_id))" in policies["chat_messages"]["select_policy"]
    assert "WITH CHECK (is_admin() OR tenant_matches(tenant_id))" in policies["feedback"]["write_policy"]
