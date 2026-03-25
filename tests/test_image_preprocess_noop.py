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
