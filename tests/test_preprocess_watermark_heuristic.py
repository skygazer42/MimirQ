from __future__ import annotations

from PIL import Image


def test_cleanup_watermark_document_auto_uses_heuristic_mask_when_no_backend(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    from app.parsing.preprocess import watermark

    input_path = tmp_path / "scan.png"
    output_path = tmp_path / "scan.clean.png"
    image = Image.new("RGB", (20, 20), "white")
    image.putpixel((10, 10), (120, 120, 120))
    image.save(input_path)

    monkeypatch.setattr(
        watermark,
        "_collect_watermark_mask_boxes",
        lambda _image: [{"bbox": [8, 8, 13, 13], "reason": "geometry"}],
    )

    changed, note, info = watermark.cleanup_watermark_document(
        input_path=input_path,
        output_path=output_path,
        backend="auto",
        model_path="",
        api_url="",
    )

    assert changed is True
    assert note == "watermark_ok"
    assert info["backend"] == "heuristic"
    assert output_path.exists()
    with Image.open(output_path) as out:
        assert out.convert("RGB").getpixel((10, 10)) == (255, 255, 255)
