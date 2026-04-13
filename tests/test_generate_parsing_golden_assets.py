from __future__ import annotations

from pathlib import Path

from PIL import Image as PILImage


def test_generate_parsing_golden_assets_writes_decodable_qr_and_barcode(tmp_path: Path) -> None:
    from app.parsing.enrich.image_understanding import decode_image_codes  # noqa: WPS433
    from scripts.generate_parsing_golden_assets import generate_assets  # noqa: WPS433

    generate_assets(tmp_path)

    qr_path = tmp_path / "qr_sheet" / "input" / "qr.png"
    barcode_path = tmp_path / "barcode_label" / "input" / "barcode.png"

    assert qr_path.exists()
    assert barcode_path.exists()

    qr_image = PILImage.open(qr_path)
    try:
        qr_out = decode_image_codes(qr_image)
    finally:
        qr_image.close()

    barcode_image = PILImage.open(barcode_path)
    try:
        barcode_out = decode_image_codes(barcode_image)
    finally:
        barcode_image.close()

    assert qr_out["visual_kind"] == "qr"
    assert qr_out["text"] == "HELLO-QR"
    assert barcode_out["visual_kind"] == "barcode"
    assert barcode_out["text"] == "5901234123457"


def test_generate_parsing_golden_assets_writes_broader_pdf_and_image_corpus(tmp_path: Path) -> None:
    from scripts.generate_parsing_golden_assets import generate_broader_assets  # noqa: WPS433

    generate_broader_assets(tmp_path)

    assert (tmp_path / "chart_pdf" / "input" / "sample.pdf").exists()
    assert (tmp_path / "diagram_pdf" / "input" / "sample.pdf").exists()
    assert (tmp_path / "qr_image" / "input" / "sample.png").exists()
    assert (tmp_path / "barcode_image" / "input" / "sample.png").exists()
    assert (tmp_path / "cross_page_table_pdf" / "input" / "sample.pdf").exists()
    assert (tmp_path / "borderless_table_scan" / "input" / "sample.png").exists()
    assert (tmp_path / "merged_header_table_pdf" / "input" / "sample.pdf").exists()
    assert (tmp_path / "table_with_leading_paragraph_pdf" / "input" / "sample.pdf").exists()
    assert (tmp_path / "two_column_pdf" / "input" / "sample.pdf").exists()
    assert (tmp_path / "header_footer_noise_pdf" / "input" / "sample.pdf").exists()
    assert (tmp_path / "mixed_layout_pdf" / "input" / "sample.pdf").exists()
    assert (tmp_path / "mixed_scan_memo_image" / "input" / "sample.png").exists()
    assert (tmp_path / "word_project_brief_docx" / "input" / "sample.docx").exists()
    assert (tmp_path / "watermark_heavy_pdf" / "input" / "sample.pdf").exists()
    assert (tmp_path / "excel_budget_sheet_xlsx" / "input" / "sample.xlsx").exists()
    assert (tmp_path / "watermark_overlay_scan_image" / "input" / "sample.png").exists()
