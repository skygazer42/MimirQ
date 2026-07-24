
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
    assert 'CREATE OR REPLACE FUNCTION "public"."is_admin"()' in functions["is_admin"]
    assert "SECURITY DEFINER" in functions["is_admin"]
    assert "SET search_path = pg_catalog" in functions["is_admin"]
    assert "auth.uid()" in functions["is_admin"]
    assert '"public"."profiles"' in functions["is_admin"]
    assert 'CREATE OR REPLACE FUNCTION "public"."tenant_matches"(resource_tenant uuid)' in functions["tenant_matches"]

    policies = bundle["policies"]
    assert set(policies.keys()) == {"chat_sessions", "chat_messages", "feedback"}
    assert 'ALTER TABLE "public"."chat_messages" ENABLE ROW LEVEL SECURITY;' == policies["chat_messages"]["enable_rls"]
    assert '"public"."is_admin"()' in policies["chat_messages"]["select_policy"]
    assert '"public"."tenant_matches"("tenant_id")' in policies["chat_messages"]["select_policy"]
    assert '"public"."is_admin"()' in policies["feedback"]["write_policy"]
    assert '"public"."tenant_matches"("tenant_id")' in policies["feedback"]["write_policy"]


def test_build_tenant_rls_bundle_escapes_literals_and_identifiers() -> None:
    bundle = build_tenant_rls_bundle(
        tenant_table='private.profiles"; DROP TABLE audit; --',
        managed_tables=['app.chat"; DROP TABLE messages; --'],
        tenant_column='tenant"id',
        role_column='role"name',
        admin_role="admin' OR true --",
    )

    is_admin = bundle["functions"]["is_admin"]
    assert '"private"."profiles""; DROP TABLE audit; --"' in is_admin
    assert '"role""name"' in is_admin
    assert "'admin'' OR true --'" in is_admin

    policy = bundle["policies"]['app.chat"; DROP TABLE messages; --']["select_policy"]
    assert '"app"."chat""; DROP TABLE messages; --"' in policy
    assert '"app.chat""; DROP TABLE messages; --_tenant_read"' in policy
    assert '"public"."tenant_matches"("tenant""id")' in policy
