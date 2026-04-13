from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.parsing.preprocess.image_preprocess import preprocess_image_document


def test_image_preprocess_disabled_is_noop(tmp_path: Path, monkeypatch) -> None:
    img = tmp_path / "sample.png"
    img.write_bytes(b"fake")

    monkeypatch.setattr(settings, "IMAGE_PREPROCESS_ENABLED", False, raising=False)
    out = preprocess_image_document(input_path=img, document_id="doc1", pdf_quality=None)
    assert out.changed is False
    assert out.output_path == str(img)


def test_image_preprocess_enabled_but_all_steps_disabled_is_noop(tmp_path: Path, monkeypatch) -> None:
    img = tmp_path / "sample.png"
    img.write_bytes(b"fake")

    monkeypatch.setattr(settings, "IMAGE_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ORIENTATION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DESKEW_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_ENABLED", False, raising=False)

    out = preprocess_image_document(input_path=img, document_id="doc1", pdf_quality=None)
    assert out.changed is False
    assert out.output_path == str(img)


def test_pdf_preprocess_skips_high_quality_pdf(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%fake\n")

    monkeypatch.setattr(settings, "IMAGE_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PREPROCESS_SKIP_HIGH_QUALITY", True, raising=False)
    monkeypatch.setattr(settings, "ORIENTATION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "DESKEW_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_ENABLED", True, raising=False)

    out = preprocess_image_document(
        input_path=pdf,
        document_id="docpdf1",
        pdf_quality={"score": 0.9, "is_scanned": False, "page_count": 1},
    )
    assert out.changed is False
    assert out.output_path == str(pdf)
    assert any(s.id == "pdf_preprocess" and "skip_high_quality" in s.note for s in (out.steps or []))


def test_image_preprocess_watermark_enabled_without_api_url_warns(tmp_path: Path, monkeypatch) -> None:
    img = tmp_path / "sample.png"
    img.write_bytes(b"fake")

    monkeypatch.setattr(settings, "IMAGE_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ORIENTATION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DESKEW_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_API_URL", "", raising=False)

    out = preprocess_image_document(input_path=img, document_id="doc1", pdf_quality=None)
    assert out.changed is False
    assert out.output_path == str(img)
    assert "watermark_api_url_missing" in (out.warnings or [])


def test_pdf_preprocess_can_apply_pagewise_watermark_cleanup_when_scanned(tmp_path: Path, monkeypatch) -> None:
    import fitz
    from PIL import Image

    pdf = tmp_path / "watermark.pdf"
    img = tmp_path / "page.png"
    Image.new("RGB", (24, 24), color=(120, 120, 120)).save(img)
    doc = fitz.open()
    page = doc.new_page(width=120, height=120)
    page.insert_image(fitz.Rect(0, 0, 120, 120), filename=str(img))
    doc.save(pdf)
    doc.close()

    monkeypatch.setattr(settings, "IMAGE_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PREPROCESS_SKIP_HIGH_QUALITY", False, raising=False)
    monkeypatch.setattr(settings, "ORIENTATION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DESKEW_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "PADDLE_OCR_PREPROCESS_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "HANDWRITING_CLEANUP_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_BACKEND", "local", raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_MODEL_PATH", "/models/watermark-lama.onnx", raising=False)
    monkeypatch.setattr(settings, "WATERMARK_PDF_ANNOT_STRIP_ENABLED", False, raising=False)

    import app.parsing.preprocess.image_preprocess as preprocess_mod

    def _fake_cleanup(**kwargs):  # noqa: ANN001
        from PIL import Image as PILImage

        out_path = kwargs["output_path"]
        PILImage.new("RGB", (24, 24), color=(200, 200, 200)).save(out_path)
        return True, "watermark_ok", {"backend": "local", "mask_box_count": 1}

    monkeypatch.setattr(preprocess_mod, "cleanup_watermark_document", _fake_cleanup, raising=True)

    out = preprocess_mod.preprocess_image_document(
        input_path=pdf,
        document_id="pdf-watermark",
        pdf_quality={"score": 0.2, "is_scanned": True, "page_count": 1},
    )

    assert out.changed is True
    assert out.output_path.endswith(".pdf")
    assert Path(out.output_path).exists()
    assert any(step.id == "watermark_removal" and step.changed is True for step in (out.steps or []))
