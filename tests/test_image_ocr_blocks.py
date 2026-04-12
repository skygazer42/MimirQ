from __future__ import annotations

from pathlib import Path

from PIL import Image


def test_add_image_ocr_blocks_appends_local_ocr_text(monkeypatch, tmp_path: Path) -> None:
    import app.parsing.enrich.image_ocr as mod  # noqa: WPS433
    from app.parsing.enrich.image_ocr import add_image_ocr_blocks  # noqa: WPS433

    image_path = tmp_path / "sample.png"
    Image.new("L", (16, 16), color=255).save(image_path)

    monkeypatch.setattr(mod, "ocr_image", lambda *_a, **_k: "Approved 72", raising=True)

    out, added, audit = add_image_ocr_blocks("![note](sample.png)\n", origin_path=tmp_path)

    assert added == 1
    assert "Image OCR:\nApproved 72" in out
    assert audit.images_attempted == 1
    assert audit.images_succeeded == 1


def test_add_image_ocr_blocks_skips_when_ocr_empty(monkeypatch, tmp_path: Path) -> None:
    import app.parsing.enrich.image_ocr as mod  # noqa: WPS433
    from app.parsing.enrich.image_ocr import add_image_ocr_blocks  # noqa: WPS433

    image_path = tmp_path / "sample.png"
    Image.new("L", (16, 16), color=255).save(image_path)

    monkeypatch.setattr(mod, "ocr_image", lambda *_a, **_k: "", raising=True)

    out, added, audit = add_image_ocr_blocks("![note](sample.png)\n", origin_path=tmp_path)

    assert out == "![note](sample.png)\n"
    assert added == 0
    assert audit.images_attempted == 1
    assert audit.images_succeeded == 0
