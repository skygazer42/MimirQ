from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.parsing.preprocess.image_preprocess import preprocess_image_document


class _FakePaddleResult:
    def __init__(self, image) -> None:  # noqa: ANN001
        self.img = {"preprocessed_img": image}
        self.json = {
            "model_settings": {
                "use_doc_orientation_classify": True,
                "use_doc_unwarping": True,
            },
            "angle": 180,
        }


class _FakePaddlePipeline:
    def __init__(self, image) -> None:  # noqa: ANN001
        self._image = image

    def predict(self, _input):  # noqa: ANN001, ANN202
        return [_FakePaddleResult(self._image)]


def test_image_preprocess_records_paddle_ocr_warning_when_backend_unavailable(tmp_path: Path, monkeypatch) -> None:
    from PIL import Image

    img = tmp_path / "sample.png"
    Image.new("RGB", (8, 8), color=(120, 120, 120)).save(img)

    monkeypatch.setattr(settings, "IMAGE_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_OCR_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_OCR_PREPROCESS_BACKEND", "local", raising=False)
    monkeypatch.setattr(settings, "ORIENTATION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DESKEW_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "HANDWRITING_CLEANUP_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_ENABLED", False, raising=False)

    import app.parsing.preprocess.paddle_doc_preprocess as paddle_mod

    monkeypatch.setattr(
        paddle_mod,
        "get_paddle_doc_preprocessor",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("paddle_missing")),
        raising=True,
    )

    out = preprocess_image_document(input_path=img, document_id="doc-paddle", pdf_quality=None)

    assert out.changed is False
    assert out.output_path == str(img)
    assert "paddle_ocr_backend_unavailable" in (out.warnings or [])
    assert any(
        step.id == "paddle_ocr_preprocess" and step.applied is True and step.changed is False and step.note.startswith("backend_unavailable")
        for step in (out.steps or [])
    )


def test_image_preprocess_applies_paddle_ocr_doc_preprocess_locally(tmp_path: Path, monkeypatch) -> None:
    from PIL import Image

    img = tmp_path / "sample.png"
    Image.new("RGB", (8, 8), color=(40, 80, 120)).save(img)
    processed = Image.new("RGB", (8, 8), color=(220, 220, 220))

    monkeypatch.setattr(settings, "IMAGE_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_OCR_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_OCR_PREPROCESS_BACKEND", "local", raising=False)
    monkeypatch.setattr(settings, "PADDLE_OCR_USE_DOC_ORIENTATION_CLASSIFY", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_OCR_USE_DOC_UNWARPING", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_OCR_USE_TEXTLINE_ORIENTATION", False, raising=False)
    monkeypatch.setattr(settings, "ORIENTATION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DESKEW_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "HANDWRITING_CLEANUP_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_ENABLED", False, raising=False)

    import app.parsing.preprocess.paddle_doc_preprocess as paddle_mod

    monkeypatch.setattr(
        paddle_mod,
        "get_paddle_doc_preprocessor",
        lambda **_kwargs: _FakePaddlePipeline(processed),
        raising=True,
    )

    out = preprocess_image_document(input_path=img, document_id="doc-paddle", pdf_quality=None)

    assert out.changed is True
    assert out.output_path != str(img)
    assert Path(out.output_path).exists()
    meta = out.meta.get("paddle_ocr_preprocess") or {}
    assert meta.get("backend") == "local"
    assert meta.get("angle") == 180
    assert meta.get("use_doc_orientation_classify") is True
    assert meta.get("use_doc_unwarping") is True
    assert any(
        step.id == "paddle_ocr_preprocess" and step.applied is True and step.changed is True and step.note == "paddle_ocr_ok"
        for step in (out.steps or [])
    )

