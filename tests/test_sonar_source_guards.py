from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_auth_dependency_source_uses_shared_invalid_token_detail_and_no_client_host_ternary():
    src = _read("app/api/dependencies/auth.py")

    assert 'INVALID_TOKEN_DETAIL = "Invalid token"' in src
    assert "return request.client.host if request.client and request.client.host else None" not in src


def test_pii_redaction_source_uses_shared_mask_constant_and_simpler_patterns():
    src = _read("app/core/pii_redaction.py")

    assert 'DEFAULT_MASK = "[REDACTED]"' in src
    assert "api[_-]?key|apikey" not in src
    assert "[ -]*?" not in src


def test_secrets_source_centralizes_sensitive_field_names():
    src = _read("app/core/secrets.py")

    assert "TOP_LEVEL_SECRET_FIELDS" in src
    assert "AUTH_SECRET_FIELDS" in src


def test_document_model_source_uses_shared_delete_orphan_cascade_constant():
    src = _read("app/models/document.py")

    assert 'DELETE_ORPHAN_CASCADE = "all, delete-orphan"' in src
    assert src.count('"all, delete-orphan"') == 1


def test_sonar_configs_keep_auto_analysis_legacy_exclusions_in_sync():
    local_scan = _read("sonar-project.properties")
    auto_scan = _read(".sonarcloud.properties")

    expected_entries = [
        "app/api/**/*",
        "app/core/**/*",
        "app/connectors/**/*",
        "app/storage/**/*",
        "app/tasks/**/*",
        "app/query/**/*",
        "app/main.py",
        "web/components/data-governance-panel.tsx",
        "web/components/data-governance/**/*",
        "web/hooks/use-chat.ts",
        "web/app/history/**/*",
        "web/components/ragviz/**/*",
        "web/components/markdown/markdown-renderer.tsx",
        "web/components/document-library/folder-tree.tsx",
        "web/app/datasets/**/*",
        "web/components/rag-trace/**/*",
        "web/components/graph/**/*",
        "web/components/chat/**/*",
        "web/components/chat-area.tsx",
        "web/lib/evidence-why-missed.ts",
        "web/lib/parsing-positions.ts",
        "web/lib/oidc.ts",
        "web/lib/oidc-pkce.ts",
        "web/lib/oidc-providers.ts",
        "web/app/api/oidc/**/*",
        "web/components/navbar.tsx",
        "web/components/sidebar.tsx",
        "web/components/pipeline-options-panel.tsx",
        "web/components/document-viewer-panel.tsx",
        "web/components/governance-profiles/**/*",
        "web/components/governance-profile-selector.tsx",
        "web/components/evaluation/**/*",
        "web/components/model-config-dialog.tsx",
        "web/components/ingestion/ingestion-detail-dialog.tsx",
        "web/app/audit/**/*",
        "web/app/settings/**/*",
        "web/app/evaluations/**/*",
        "web/app/observability/**/*",
        "web/app/reports/**/*",
        "web/app/usage/**/*",
        "web/app/diagnostics/**/*",
        "web/app/auth/**/*",
        "web/lib/chunk-strategies.ts",
        "web/lib/dataset-health-export.ts",
        "web/lib/openapi-request.ts",
        "web/lib/api-errors.ts",
        "web/lib/saml-session.ts",
        "web/lib/parser-compat.ts",
        "web/lib/zip.ts",
        "web/lib/graph-algorithms.ts",
        "web/lib/governance-profile-utils.ts",
        "web/lib/chunk-strategy-params.ts",
        "**/*.test.ts",
        "**/*.test.tsx",
        "**/*.spec.ts",
        "**/*.spec.tsx",
        "web/types/index.ts",
        "web/types/backend.ts",
        "web/hooks/use-resize-observer.ts",
        "web/components/command-menu.tsx",
        "web/components/theme-customizer.tsx",
        "web/components/rag/retrieve-preview-panel.tsx",
    ]

    for entry in expected_entries:
        assert entry in local_scan
        assert entry in auto_scan
