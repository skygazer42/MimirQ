from collections.abc import Iterable

_LEGACY_TYPES = {"doc", "xls", "ppt"}
_IMAGE_TYPES = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff", "tif", "pptx"}
_TABLE_TYPES = {"csv", "xls", "xlsx"}
_TEXTLIKE_TYPES = {
    "txt",
    "md",
    "rst",
    "adoc",
    "asciidoc",
    "tex",
    "yaml",
    "yml",
    "toml",
    "ini",
    "cfg",
    "conf",
    "env",
    "properties",
    "sql",
    "log",
    "patch",
    "diff",
    "json",
    "jsonl",
    "ndjson",
    "xml",
    "html",
    "htm",
    "docx",
    "eml",
    "msg",
}


def _normalized_findings(findings: Iterable[str] | None) -> set[str]:
    return {str(item or "").strip().lower() for item in (findings or []) if str(item or "").strip()}


def classify_parse_failure_kind(*, file_type: str, error_message: str | None) -> str:
    ft = str(file_type or "").strip().lower().lstrip(".")
    msg = str(error_message or "").strip().lower()
    if ft in _LEGACY_TYPES or "unsupportedformat" in msg or "legacy" in msg:
        return "legacy_format"
    if "password" in msg or "encrypted" in msg or "permission" in msg:
        return "password_protected"
    if any(token in msg for token in ("badzip", "corrupt", "unreadable", "damaged", "invalidpdf", "pdfsyntax")):
        return "corrupted_or_unreadable"
    return "other_parse_failure"


def infer_primary_tag(*, file_type: str, findings: Iterable[str] | None) -> str:
    ft = str(file_type or "").strip().lower().lstrip(".")
    fset = _normalized_findings(findings)
    if "parse_failed" in fset:
        return "Parse_Failed"
    if (
        ft in _TABLE_TYPES
        or {"large_spreadsheet", "wide_spreadsheet", "many_sheets_spreadsheet", "merged_heavy_spreadsheet"} & fset
    ):
        return "Table_Heavy"
    if ft == "pdf" and {"pdf_scanned", "pdf_mixed", "pdf_low_density", "pdf_unknown", "pdf_encrypted"} & fset:
        return "Scan_PDF"
    if ft in _IMAGE_TYPES or "image_heavy" in fset:
        return "Image_Heavy"
    if ft in _TEXTLIKE_TYPES:
        return "Clean_Markdown"
    return "Parse_Failed" if "parse_failed" in fset else "Clean_Markdown"


def infer_processing_paths(*, primary_tag: str, findings: Iterable[str] | None) -> list[str]:
    fset = _normalized_findings(findings)
    out: list[str] = []

    if primary_tag == "Scan_PDF":
        out.append("ocr_or_vlm_path")
    elif primary_tag == "Table_Heavy":
        out.append("structured_table_path")
    elif primary_tag == "Parse_Failed":
        out.append("fallback_parser_path")
    elif primary_tag == "Image_Heavy":
        out.append("ocr_or_vlm_path")

    if {"pii", "secrets", "near_dup", "exact_dup", "parse_failed"} & fset:
        if "manual_review" not in out:
            out.append("manual_review")

    return out


__all__ = [
    "classify_parse_failure_kind",
    "infer_primary_tag",
    "infer_processing_paths",
]
