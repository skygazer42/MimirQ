import shutil


def _check_import(module: str) -> tuple[bool, str]:
    try:
        __import__(module)
        return True, "ok"
    except Exception as exc:
        return False, str(exc)[:160]


def main() -> int:
    from app.core.config import settings

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
            "configured" if deepseek_enabled and deepseek_configured else ("missing SILICONFLOW_API_KEY" if deepseek_enabled else "disabled"),
        )
    )

    etl4llm_enabled = bool(getattr(settings, "ETL4LLM_ENABLED", False))
    etl4llm_configured = bool((getattr(settings, "ETL4LLM_API_URL", "") or "").strip())
    rows.append(
        (
            "etl4llm",
            "on" if etl4llm_enabled else "off",
            "configured" if etl4llm_enabled and etl4llm_configured else ("missing ETL4LLM_API_URL" if etl4llm_enabled else "disabled"),
        )
    )

    ok, msg = _check_import("markitdown")
    rows.append(("markitdown", "on" if settings.MARKITDOWN_ENABLED else "off", "installed" if ok else msg))

    ok, msg = _check_import("docling")
    rows.append(("docling", "on" if getattr(settings, "DOCLING_ENABLED", False) else "off", "installed" if ok else msg))

    mineru_configured = bool(settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL))
    rows.append(("mineru", "on" if settings.MINERU_ENABLED else "off", "configured" if mineru_configured else "missing api_token or local_server_url"))

    if bool(getattr(settings, "RAPIDOCR_ENABLED", False)):
        ok, msg = _check_import("rapidocr_onnxruntime")
        rows.append(("rapidocr", "on", "installed" if ok else msg))
    else:
        rows.append(("rapidocr", "off", "disabled"))

    cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
    cli_ok = bool(shutil.which(cli))
    magicpdf_configured = bool(getattr(settings, "MAGIC_PDF_ENABLED", False) and cli_ok)
    rows.append(("magicpdf", "on" if getattr(settings, "MAGIC_PDF_ENABLED", False) else "off", "configured" if magicpdf_configured else ("missing cli" if getattr(settings, "MAGIC_PDF_ENABLED", False) else "disabled")))

    col1 = max(len(r[0]) for r in rows)
    col2 = max(len(r[1]) for r in rows)

    print(f"{'backend':<{col1}}  {'enabled':<{col2}}  status")
    print(f"{'-'*col1}  {'-'*col2}  {'-'*30}")
    for backend, enabled, status in rows:
        print(f"{backend:<{col1}}  {enabled:<{col2}}  {status}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
