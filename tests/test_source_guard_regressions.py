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
