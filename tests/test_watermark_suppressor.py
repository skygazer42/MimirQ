from __future__ import annotations

from PIL import Image

from app.parsing.enrich.watermark_suppressor import suppress_watermark_regions


def test_suppress_watermark_regions_whitens_masked_area_without_touching_source() -> None:
    image = Image.new("RGB", (20, 20), "white")
    image.putpixel((10, 10), (120, 120, 120))

    result = suppress_watermark_regions(
        image,
        boxes=[{"bbox": [8, 8, 13, 13], "reason": "test"}],
    )

    assert result.changed is True
    assert result.masked_regions == 1
    assert result.image.getpixel((10, 10)) == (255, 255, 255)
    assert image.getpixel((10, 10)) == (120, 120, 120)
