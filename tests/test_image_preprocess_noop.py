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

