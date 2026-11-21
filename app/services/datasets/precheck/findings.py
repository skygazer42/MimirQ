"""Classify precheck findings and project their stable report summaries."""

from collections.abc import Iterable
from typing import Any

_LEGACY_TYPES = {"doc", "xls", "ppt"}
_IMAGE_TYPES = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff", "tif", "pptx"}
_TABLE_TYPES = {"csv", "xls", "xlsx"}


def _normalized_findings(findings: Iterable[str] | None) -> set[str]:
    return {item.strip().lower() for item in (findings or []) if item.strip()}


def classify_parse_failure_kind(*, file_type: str, error_message: str | None) -> str:
    ft = file_type.strip().lower().lstrip(".")
    if ft in _LEGACY_TYPES:
        return "legacy_format"
    if error_message is None:
        return "other_parse_failure"
    msg = error_message.strip().lower()
    if "unsupportedformat" in msg or "legacy" in msg:
        return "legacy_format"
    if "password" in msg or "encrypted" in msg or "permission" in msg:
        return "password_protected"
    if any(token in msg for token in ("badzip", "corrupt", "unreadable", "damaged", "invalidpdf", "pdfsyntax")):
        return "corrupted_or_unreadable"
    return "other_parse_failure"


def infer_primary_tag(*, file_type: str, findings: Iterable[str] | None) -> str:
    ft = file_type.strip().lower().lstrip(".")
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
    return "Clean_Markdown"


def infer_processing_paths(*, primary_tag: str, findings: Iterable[str] | None) -> list[str]:
    fset = _normalized_findings(findings)
    out: list[str] = []

    if primary_tag in {"Scan_PDF", "Image_Heavy"}:
        out.append("ocr_or_vlm_path")
    elif primary_tag == "Table_Heavy":
        out.append("structured_table_path")
    elif primary_tag == "Parse_Failed":
        out.append("fallback_parser_path")
    if {"pii", "secrets", "near_dup", "exact_dup", "parse_failed"} & fset:
        out.append("manual_review")

    return out


def risk_buckets_for_file(*, file_type: str, findings: Iterable[str] | None) -> list[str]:
    ft = file_type.strip().lower()
    fset = _normalized_findings(findings)

    buckets: set[str] = set()

    # OCR / PDF quality.
    if ft == "pdf" and ({"pdf_scanned", "pdf_unknown"} & fset):
        buckets.add("ocr")

    # Garbage / decode failures.
    if "gibberish_text" in fset or "parse_failed" in fset:
        buckets.add("garbage")

    # Low signal density.
    if "low_density_text" in fset or "pdf_low_density" in fset:
        buckets.add("low_density")

    # Web/HTML boilerplate (navigation/headers/scripts).
    if ft in {"html", "htm"}:
        buckets.add("boilerplate")

    # Table-like / structured data.
    if ft in {"csv", "xls", "xlsx"}:
        buckets.add("table_heavy")

    return sorted(buckets)


def _safe_int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def summarize_near_dup_payload(payload: object) -> dict[str, Any]:
    """
    Build a compact summary from a near-duplicate artifact payload.

    Returns a stable dict so it can be embedded in precheck summary JSON and reports.
    """
    empty = {
        "enabled": False,
        "threshold": 0,
        "pairs": 0,
        "clusters": 0,
        "affected_files": 0,
        "largest_cluster_size": 0,
        "keep_candidates_sample": [],
    }

    if not isinstance(payload, dict) or not payload:
        return empty

    clusters = payload.get("clusters") if isinstance(payload.get("clusters"), list) else []
    threshold = _safe_int(payload.get("threshold"))
    pairs = _safe_int(payload.get("pairs_returned"))
    raw_pairs = payload.get("pairs")
    if pairs <= 0 and isinstance(raw_pairs, list):
        pairs = len(raw_pairs)

    affected: set[str] = set()
    largest = 0
    keep_candidates: list[str] = []
    seen_keep: set[str] = set()

    for c in clusters:
        if not isinstance(c, dict):
            continue
        members_raw = c.get("members")
        members: list[str] = []
        if isinstance(members_raw, list):
            for m in members_raw:
                s = m.strip()
                if s:
                    members.append(s)
        affected.update(members)
        largest = max(largest, len(members))

        kc = c["keep_candidate"].strip()
        if kc and kc not in seen_keep:
            keep_candidates.append(kc)
            seen_keep.add(kc)

    cluster_count = _safe_int(payload.get("clusters_returned"))
    if cluster_count <= 0:
        cluster_count = len(clusters)

    return {
        "enabled": True,
        "threshold": threshold,
        "pairs": pairs,
        "clusters": cluster_count,
        "affected_files": len(affected),
        "largest_cluster_size": largest,
        "keep_candidates_sample": keep_candidates[:20],
    }


__all__ = [
    "classify_parse_failure_kind",
    "infer_primary_tag",
    "infer_processing_paths",
    "risk_buckets_for_file",
    "summarize_near_dup_payload",
]
