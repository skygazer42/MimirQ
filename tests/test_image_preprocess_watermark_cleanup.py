from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.parsing.preprocess.image_preprocess import preprocess_image_document
from app.parsing.preprocess.model_loader import LoadedModel


class _FakeOrtValue:
    def __init__(self, name: str, shape=None) -> None:  # noqa: ANN001
        self.name = name
        self.shape = shape


class _FakeWatermarkSession:
    def get_inputs(self) -> list[_FakeOrtValue]:
        return [
            _FakeOrtValue("image", [1, 3, 8, 8]),
            _FakeOrtValue("mask", [1, 1, 8, 8]),
        ]

    def run(self, _output_names, feeds):  # noqa: ANN001, ANN202
        import numpy as np

        image = np.array(feeds["image"], dtype=np.float32, copy=True)
        mask = np.array(feeds["mask"], dtype=np.float32, copy=True)
        mask3 = np.repeat(mask, 3, axis=1)
        # Brighten masked region so output deterministically differs.
        return [np.clip(image + (mask3 * 0.75), 0.0, 1.0)]


class _FakeWatermarkLoader:
    def load_onnx(self, *, name: str, model_path: str) -> LoadedModel:
        return LoadedModel(name=name, backend="onnxruntime", handle=_FakeWatermarkSession())


def test_image_preprocess_records_watermark_warning_when_local_model_missing(tmp_path: Path, monkeypatch) -> None:
    from PIL import Image

    img = tmp_path / "watermark.png"
    Image.new("RGB", (8, 8), color=(150, 150, 150)).save(img)

    monkeypatch.setattr(settings, "IMAGE_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ORIENTATION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DESKEW_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "HANDWRITING_CLEANUP_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_BACKEND", "local", raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_MODEL_PATH", "", raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_API_URL", "", raising=False)

    out = preprocess_image_document(input_path=img, document_id="doc-watermark", pdf_quality=None)

    assert out.changed is False
    assert out.output_path == str(img)
    assert "watermark_model_missing" in (out.warnings or [])
    assert any(
        step.id == "watermark_removal" and step.applied is True and step.changed is False and step.note == "missing_model_path"
        for step in (out.steps or [])
    )


def test_image_preprocess_applies_watermark_cleanup_via_local_onnx_backend(tmp_path: Path, monkeypatch) -> None:
    from PIL import Image

    img = tmp_path / "watermark.png"
    Image.new("RGB", (8, 8), color=(60, 60, 60)).save(img)

    monkeypatch.setattr(settings, "IMAGE_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ORIENTATION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DESKEW_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "HANDWRITING_CLEANUP_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_BACKEND", "local", raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_MODEL_PATH", "/models/watermark-lama.onnx", raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_API_URL", "", raising=False)

    import app.parsing.preprocess.watermark as watermark_mod

    monkeypatch.setattr(watermark_mod, "get_preprocess_model_loader", lambda: _FakeWatermarkLoader(), raising=True)
    monkeypatch.setattr(
        watermark_mod,
        "_collect_watermark_mask_boxes",
        lambda *_args, **_kwargs: [{"bbox": [1, 1, 6, 6], "text": "DRAFT", "reason": "keyword", "score": 1.0}],
        raising=True,
    )

    out = preprocess_image_document(input_path=img, document_id="doc-watermark", pdf_quality=None)

    assert out.changed is True
    assert out.output_path != str(img)
    assert Path(out.output_path).exists()
    info = out.meta.get("watermark_removal") or {}
    assert info.get("backend") == "local"
    assert info.get("model_backend") == "onnxruntime"
    assert int(info.get("mask_box_count") or 0) == 1
    assert any(
        step.id == "watermark_removal" and step.applied is True and step.changed is True and step.note == "watermark_ok"
        for step in (out.steps or [])
    )

