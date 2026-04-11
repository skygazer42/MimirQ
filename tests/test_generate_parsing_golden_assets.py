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
