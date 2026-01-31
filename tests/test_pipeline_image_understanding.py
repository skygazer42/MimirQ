from app.services.pipeline_config import build_pipeline_metadata, parse_pipeline_from_metadata, resolve_pipeline_options
from app.types.pipeline import PipelineOptions


def test_pipeline_metadata_roundtrip_image_understanding_fields() -> None:
    opts = PipelineOptions(
        image_caption_enabled=True,
        image_ocr_enabled=True,
        image_ocr_max_chars=1234,
        image_ocr_max_images=12,
    )
    meta = build_pipeline_metadata(opts)
    parsed = parse_pipeline_from_metadata({"pipeline": meta})

    assert parsed.image_caption_enabled is True
    assert parsed.image_ocr_enabled is True
    assert parsed.image_ocr_max_chars == 1234
    assert parsed.image_ocr_max_images == 12


def test_resolve_pipeline_options_uses_overrides_for_image_understanding_fields() -> None:
    eff = resolve_pipeline_options(
        PipelineOptions(
            image_caption_enabled=True,
            image_ocr_enabled=True,
            image_ocr_max_chars=222,
            image_ocr_max_images=3,
        )
    )
    assert eff.image_caption_enabled is True
    assert eff.image_ocr_enabled is True
    assert eff.image_ocr_max_chars == 222
    assert eff.image_ocr_max_images == 3

