from __future__ import annotations

from app.parsing.enrich.document_noise_rules import classify_document_noise_text


def test_classify_document_noise_text_recognizes_pdf_export_boilerplate() -> None:
    match = classify_document_noise_text("微信文章在线转PDF")

    assert match is not None
    assert match.kind == "pdf_export_noise"
    assert match.to_metadata()["rule"] == "wechat2pdf"


def test_classify_document_noise_text_ignores_normal_short_table_header() -> None:
    assert classify_document_noise_text("项目") is None
