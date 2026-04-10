from __future__ import annotations

from PIL import Image, ImageDraw

from app.core.config import settings
from app.parsing.enrich.seal_recognition import _DEFAULT_MODEL_DIR, _resolve_model_dir, detect_seal_regions


def test_detect_seal_regions_finds_red_stamp_candidate() -> None:
    image = Image.new("RGB", (400, 400), color="white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((110, 110, 290, 290), outline=(220, 0, 0), width=18)
    draw.ellipse((150, 150, 250, 250), outline=(220, 0, 0), width=8)

    regions = detect_seal_regions(image)

    assert len(regions) >= 1
    first = regions[0]
    assert first.bbox[2] > first.bbox[0]
    assert first.bbox[3] > first.bbox[1]
    assert first.detection_score > 0


def test_resolve_model_dir_falls_back_to_bundled_deepdoc_model(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SEAL_RECOGNITION_MODEL_DIR", "", raising=False)

    resolved = _resolve_model_dir()

    assert resolved == _DEFAULT_MODEL_DIR
    assert resolved is not None
    assert (resolved / "encoder_model.onnx").exists()
    assert (resolved / "decoder_model.onnx").exists()
    assert (resolved / "vocab.json").exists()
