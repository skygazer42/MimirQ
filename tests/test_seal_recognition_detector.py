from __future__ import annotations

from PIL import Image, ImageDraw

from app.parsing.enrich.seal_recognition import detect_seal_regions


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
