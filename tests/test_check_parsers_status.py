from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "check_parsers.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("check_parsers", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_mineru_status_reports_import_failure_for_configured_runtime() -> None:
    mod = _load_module()
    status = mod._mineru_status(  # type: ignore[attr-defined]
        enabled=True,
        local_server_url="",
        api_token="token",
        token_expired=False,
        token_expiry_text=None,
        import_ok=False,
        import_message="libGL.so.1: cannot open shared object file",
    )
    assert status == "import failed: libGL.so.1: cannot open shared object file"


def test_mineru_status_keeps_expired_token_message_ahead_of_import_checks() -> None:
    mod = _load_module()
    status = mod._mineru_status(  # type: ignore[attr-defined]
        enabled=True,
        local_server_url="",
        api_token="token",
        token_expired=True,
        token_expiry_text="2026-01-24T16:19:46Z",
        import_ok=False,
        import_message="libGL.so.1: cannot open shared object file",
    )
    assert status == "api_token expired at 2026-01-24T16:19:46Z"


def test_textin_status_requires_credentials_when_enabled() -> None:
    mod = _load_module()
    status = mod._textin_status(  # type: ignore[attr-defined]
        enabled=True,
        api_url="https://api.textin.com/ai/service/v1/pdf_to_markdown",
        app_id="",
        secret_code="",
    )
    assert status == "missing TEXTIN_APP_ID"


def test_textin_status_reports_configured_only_with_url_and_credentials() -> None:
    mod = _load_module()
    status = mod._textin_status(  # type: ignore[attr-defined]
        enabled=True,
        api_url="https://api.textin.com/ai/service/v1/pdf_to_markdown",
        app_id="demo-app-id",
        secret_code="demo-secret",
    )
    assert status == "configured"


def test_magicpdf_status_requires_cli_and_models(tmp_path: Path) -> None:
    mod = _load_module()
    assert (
        mod._magicpdf_status(enabled=True, cli_path=None, models_dir=tmp_path)  # type: ignore[attr-defined]
        == "missing cli"
    )
    assert (
        mod._magicpdf_status(enabled=True, cli_path="/usr/bin/magic-pdf", models_dir=None)  # type: ignore[attr-defined]
        == "missing models"
    )
    status = mod._magicpdf_status(  # type: ignore[attr-defined]
        enabled=True,
        cli_path="/usr/bin/magic-pdf",
        models_dir=tmp_path,
    )
    assert status == f"configured (models: {tmp_path})"
