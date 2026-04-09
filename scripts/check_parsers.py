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


def main() -> int:
    from app.core.config import settings
    from app.core.jwt_inspect import format_unix_ts_utc, try_get_jwt_exp
    from app.parsing.utils.cli import resolve_cli_command

    rows: list[tuple[str, str, str]] = []

    rows.append(("basic", "on", "built-in"))

    ok, msg = _check_import("app.deepdoc.parser")
    rows.append(("deepdoc", "on" if settings.DEEPDOC_ENABLED else "off", "available" if ok else msg))

    deepseek_enabled = bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False))
    deepseek_configured = bool((getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip())
    rows.append(
        (
            "deepseek_ocr",
            "on" if deepseek_enabled else "off",
            _configured_status(deepseek_enabled, deepseek_configured, "missing SILICONFLOW_API_KEY"),
        )
    )

    etl4llm_enabled = bool(getattr(settings, "ETL4LLM_ENABLED", False))
    etl4llm_configured = bool((getattr(settings, "ETL4LLM_API_URL", "") or "").strip())
    rows.append(
        (
            "etl4llm",
            "on" if etl4llm_enabled else "off",
            _configured_status(etl4llm_enabled, etl4llm_configured, "missing ETL4LLM_API_URL"),
        )
    )

    marker_enabled = bool(getattr(settings, "MARKER_ENABLED", False))
    marker_configured = bool((getattr(settings, "MARKER_API_URL", "") or "").strip())
    rows.append(
        (
            "marker",
            "on" if marker_enabled else "off",
            _configured_status(marker_enabled, marker_configured, "missing MARKER_API_URL"),
        )
    )

    paddlevl_enabled = bool(getattr(settings, "PADDLE_VL_ENABLED", False))
    paddlevl_configured = bool((getattr(settings, "PADDLE_VL_API_URL", "") or "").strip())
    rows.append(
        (
            "paddle_vl",
            "on" if paddlevl_enabled else "off",
            _configured_status(paddlevl_enabled, paddlevl_configured, "missing PADDLE_VL_API_URL"),
        )
    )

    olmocr_enabled = bool(getattr(settings, "OLMOCR_ENABLED", False))
    olmocr_configured = bool((getattr(settings, "OLMOCR_API_URL", "") or "").strip())
    rows.append(
        (
            "olmocr",
            "on" if olmocr_enabled else "off",
            _configured_status(olmocr_enabled, olmocr_configured, "missing OLMOCR_API_URL"),
        )
    )

    ok, msg = _check_import("markitdown")
    rows.append(("markitdown", "on" if settings.MARKITDOWN_ENABLED else "off", "installed" if ok else msg))

    pandoc_enabled = bool(getattr(settings, "PANDOC_ENABLED", False))
    pandoc_cli = (getattr(settings, "PANDOC_CLI", "") or "pandoc").strip() or "pandoc"
    pandoc_path = resolve_cli_command(pandoc_cli)
    rows.append(
        (
            "pandoc",
            "on" if pandoc_enabled else "off",
            _configured_cli_status(pandoc_enabled, pandoc_path),
        )
    )

    lo_enabled = bool(getattr(settings, "LIBREOFFICE_ENABLED", False))
    lo_cli = (getattr(settings, "LIBREOFFICE_CLI", "") or "soffice").strip() or "soffice"
    lo_path = resolve_cli_command(lo_cli)
    rows.append(
        (
            "libreoffice",
            "on" if lo_enabled else "off",
            _configured_cli_status(lo_enabled, lo_path),
        )
    )

    ok, msg = _check_import("docling")
    rows.append(("docling", "on" if getattr(settings, "DOCLING_ENABLED", False) else "off", "installed" if ok else msg))

    mineru_enabled = bool(getattr(settings, "MINERU_ENABLED", False))
    mineru_token = (getattr(settings, "MINERU_API_TOKEN", "") or "").strip()
    mineru_exp = try_get_jwt_exp(mineru_token) if mineru_token else None
    mineru_token_expired = bool(mineru_exp is not None and int(mineru_exp) <= int(time.time()))
    mineru_import_ok, mineru_import_msg = _check_import("app.parsing.parsers.mineru_parser")
    mineru_status = _mineru_status(
        enabled=mineru_enabled,
        local_server_url=(getattr(settings, "MINERU_LOCAL_SERVER_URL", "") or "").strip(),
        api_token=mineru_token,
        token_expired=mineru_token_expired,
        token_expiry_text=format_unix_ts_utc(int(mineru_exp)) if mineru_exp is not None else None,
        import_ok=mineru_import_ok,
        import_message=mineru_import_msg,
    )
    rows.append(("mineru", "on" if mineru_enabled else "off", mineru_status))

    if bool(getattr(settings, "RAPIDOCR_ENABLED", False)):
        ok, msg = _check_import("rapidocr_onnxruntime")
        rows.append(("rapidocr", "on", "installed" if ok else msg))
    else:
        rows.append(("rapidocr", "off", "disabled"))

    cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
    cli_ok = bool(resolve_cli_command(cli))
    magicpdf_configured = bool(getattr(settings, "MAGIC_PDF_ENABLED", False) and cli_ok)
    rows.append(
        (
            "magicpdf",
            "on" if getattr(settings, "MAGIC_PDF_ENABLED", False) else "off",
            _configured_status(bool(getattr(settings, "MAGIC_PDF_ENABLED", False)), magicpdf_configured, _MISSING_CLI),
        )
    )

    col1 = max(len(r[0]) for r in rows)
    col2 = max(len(r[1]) for r in rows)

    print(f"{'backend':<{col1}}  {'enabled':<{col2}}  status")
    print(f"{'-'*col1}  {'-'*col2}  {'-'*30}")
    for backend, enabled, status in rows:
        print(f"{backend:<{col1}}  {enabled:<{col2}}  {status}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
