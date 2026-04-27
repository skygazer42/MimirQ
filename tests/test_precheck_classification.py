from __future__ import annotations


def test_infer_primary_tag_and_processing_paths_for_scanned_pdf() -> None:
    from app.services.dataset_precheck_classification import (
        infer_primary_tag,
        infer_processing_paths,
    )

    findings = ["pdf_scanned", "pii"]
    tag = infer_primary_tag(file_type="pdf", findings=findings)
    paths = infer_processing_paths(primary_tag=tag, findings=findings)

    assert tag == "Scan_PDF"
    assert paths == ["ocr_or_vlm_path", "manual_review"]


def test_classify_parse_failure_distinguishes_common_failure_kinds() -> None:
    from app.services.dataset_precheck_classification import classify_parse_failure_kind

    assert classify_parse_failure_kind(file_type="doc", error_message="parse_failed:UnsupportedFormatError") == "legacy_format"
    assert classify_parse_failure_kind(file_type="pdf", error_message="parse_failed:PasswordProtectedError") == "password_protected"
    assert classify_parse_failure_kind(file_type="docx", error_message="parse_failed:BadZipFile") == "corrupted_or_unreadable"
    assert classify_parse_failure_kind(file_type="txt", error_message="parse_failed:RuntimeError") == "other_parse_failure"
