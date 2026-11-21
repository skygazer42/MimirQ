import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_MISSING_CLI = "missing cli"


def _check_import(module: str) -> tuple[bool, str]:
    try:
        __import__(module)
        return True, "ok"
    except Exception as exc:
        return False, str(exc)[:160]


def _configured_status(enabled: bool, configured: bool, missing_message: str) -> str:
    if enabled and configured:
        return "configured"
    if enabled:
        return missing_message
    return "disabled"


def _configured_cli_status(enabled: bool, cli_path: str | None) -> str:
    if enabled and cli_path:
        return f"configured ({cli_path})"
    if enabled:
        return _MISSING_CLI
    return "disabled"


def _textin_status(
    *,
    enabled: bool,
    api_url: str | None,
    app_id: str | None,
    secret_code: str | None,
) -> str:
    if not enabled:
        return "disabled"
    if not (api_url or "").strip():
        return "missing TEXTIN_API_URL"
    if not (app_id or "").strip():
        return "missing TEXTIN_APP_ID"
    if not (secret_code or "").strip():
        return "missing TEXTIN_SECRET_CODE"
    return "configured"


def _mineru_status(
    *,
    enabled: bool,
    local_server_url: str | None,
    api_token: str | None,
    token_expired: bool,
    token_expiry_text: str | None,
    import_ok: bool,
    import_message: str,
) -> str:
    if not enabled:
        return "disabled"
    if local_server_url:
        return "configured (local)" if import_ok else f"import failed: {import_message}"
    if not api_token:
        return "missing api_token or local_server_url"
    if token_expired and token_expiry_text:
        return f"api_token expired at {token_expiry_text}"
    if not import_ok:
        return f"import failed: {import_message}"
    return "configured"


def _magicpdf_status(
    *,
    enabled: bool,
    cli_path: str | None,
    models_dir: Path | None,
    api_url: str = "",
) -> str:
    if not enabled:
        return "disabled"
    if api_url.strip():
        return "configured (service)"
    if not cli_path:
        return _MISSING_CLI
    if not models_dir:
        return "missing models"
    return f"configured (models: {models_dir})"


def main() -> int:
    from app.infrastructure.config import settings
    from app.infrastructure.security.jwt_inspect import format_unix_ts_utc, try_get_jwt_exp
    from app.rag.ingestion.parsing.parsers.magic_pdf_parser import (
        magicpdf_service_configured,
        resolve_magicpdf_models_dir,
    )
    from app.rag.ingestion.parsing.utils.cli import resolve_cli_command

    rows: list[tuple[str, str, str]] = []

    rows.append(("basic", "on", "built-in"))

    ok, msg = _check_import("app.rag.ingestion.parsing.parsers.deepdoc_parser")
    rows.append(("deepdoc", "on" if settings.DEEPDOC_ENABLED else "off", "available" if ok else msg))

    service_checks = (
        ("deepseek_ocr", settings.DEEPSEEK_OCR_ENABLED, settings.SILICONFLOW_API_KEY, "missing SILICONFLOW_API_KEY"),
        ("etl4llm", settings.ETL4LLM_ENABLED, settings.ETL4LLM_API_URL, "missing ETL4LLM_API_URL"),
        ("marker", settings.MARKER_ENABLED, settings.MARKER_API_URL, "missing MARKER_API_URL"),
        ("paddle_vl", settings.PADDLE_VL_ENABLED, settings.PADDLE_VL_API_URL, "missing PADDLE_VL_API_URL"),
        ("olmocr", settings.OLMOCR_ENABLED, settings.OLMOCR_API_URL, "missing OLMOCR_API_URL"),
    )
    for name, enabled, required, missing in service_checks:
        status = _configured_status(enabled, bool(required.strip()), missing)
        rows.append((name, "on" if enabled else "off", status))

    textin_enabled = settings.TEXTIN_ENABLED
    rows.append(
        (
            "textin",
            "on" if textin_enabled else "off",
            _textin_status(
                enabled=textin_enabled,
                api_url=settings.TEXTIN_API_URL,
                app_id=settings.TEXTIN_APP_ID,
                secret_code=settings.TEXTIN_SECRET_CODE,
            ),
        )
    )

    ok, msg = _check_import("markitdown")
    rows.append(("markitdown", "on" if settings.MARKITDOWN_ENABLED else "off", "installed" if ok else msg))

    pandoc_enabled = settings.PANDOC_ENABLED
    pandoc_cli = settings.PANDOC_CLI.strip() or "pandoc"
    pandoc_path = resolve_cli_command(pandoc_cli)
    rows.append(
        (
            "pandoc",
            "on" if pandoc_enabled else "off",
            _configured_cli_status(pandoc_enabled, pandoc_path),
        )
    )

    lo_enabled = settings.LIBREOFFICE_ENABLED
    lo_cli = settings.LIBREOFFICE_CLI.strip() or "soffice"
    lo_path = resolve_cli_command(lo_cli)
    rows.append(
        (
            "libreoffice",
            "on" if lo_enabled else "off",
            _configured_cli_status(lo_enabled, lo_path),
        )
    )

    docling_enabled = settings.DOCLING_ENABLED
    docling_api_url = settings.DOCLING_API_URL.strip()
    if not docling_enabled:
        docling_status = "disabled"
    elif docling_api_url:
        docling_status = f"configured (service: {docling_api_url})"
    else:
        docling_status = "missing api_url"
    rows.append(("docling", "on" if docling_enabled else "off", docling_status))

    mineru_enabled = settings.MINERU_ENABLED
    mineru_token = settings.MINERU_API_TOKEN.strip()
    mineru_exp = try_get_jwt_exp(mineru_token) if mineru_token else None
    mineru_token_expired = mineru_exp is not None and mineru_exp <= time.time()
    mineru_import_ok, mineru_import_msg = _check_import("app.rag.ingestion.parsing.parsers.mineru_parser")
    mineru_status = _mineru_status(
        enabled=mineru_enabled,
        local_server_url=settings.MINERU_LOCAL_SERVER_URL.strip(),
        api_token=mineru_token,
        token_expired=mineru_token_expired,
        token_expiry_text=format_unix_ts_utc(mineru_exp) if mineru_exp is not None else None,
        import_ok=mineru_import_ok,
        import_message=mineru_import_msg,
    )
    rows.append(("mineru", "on" if mineru_enabled else "off", mineru_status))

    if settings.RAPIDOCR_ENABLED:
        ok, msg = _check_import("rapidocr_onnxruntime")
        rows.append(("rapidocr", "on", "installed" if ok else msg))
    else:
        rows.append(("rapidocr", "off", "disabled"))

    cli = settings.MAGIC_PDF_CLI.strip() or "magic-pdf"
    cli_path = resolve_cli_command(cli)
    magicpdf_models_dir = resolve_magicpdf_models_dir(settings.MAGIC_PDF_MODELS_DIR)
    rows.append(
        (
            "magicpdf",
            "on" if settings.MAGIC_PDF_ENABLED else "off",
            _magicpdf_status(
                enabled=settings.MAGIC_PDF_ENABLED,
                cli_path=str(cli_path) if cli_path else None,
                models_dir=magicpdf_models_dir,
                api_url=settings.MAGIC_PDF_API_URL if magicpdf_service_configured(settings.MAGIC_PDF_API_URL) else "",
            ),
        )
    )

    col1 = max(len(r[0]) for r in rows)
    col2 = max(len(r[1]) for r in rows)

    print(f"{'backend':<{col1}}  {'enabled':<{col2}}  status")
    print(f"{'-' * col1}  {'-' * col2}  {'-' * 30}")
    for backend, enabled, status in rows:
        print(f"{backend:<{col1}}  {enabled:<{col2}}  {status}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
