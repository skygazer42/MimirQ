import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.core.config import settings
from app.parsing.enrich import (
    chart_to_data,
    formula_ocr,
    image_caption,
    image_code,
    image_understanding,
    vlm_image_caption,
)
from app.parsing.enrich.table_cell_schema import TableCell, TableExtraction
from app.parsing.enrich.table_image_algorithms import bind_ocr_lines_to_table_cells


def _write_png(path: Path, *, color: str = "white", size: tuple[int, int] = (8, 8)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    data = buffer.getvalue()
    path.write_bytes(data)
    return data


@pytest.mark.parametrize(
    ("reader", "expect_reason"),
    [
        (chart_to_data._safe_read_local_image_bytes, "path_outside_origin"),
        (formula_ocr._safe_read_local_image_bytes, "path_outside_origin"),
        (image_code._safe_read_local_image_bytes, "path_outside_origin"),
    ],
)
def test_safe_read_local_image_bytes_blocks_path_escape(
    tmp_path: Path,
    reader,
    expect_reason: str,
) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    outside = tmp_path / "outside.png"
    _write_png(outside)

    data, reason = reader(src="../outside.png", origin_path=origin, max_bytes=10_000)

    assert data is None
    assert reason == expect_reason


def test_safe_read_local_image_bytes_accepts_local_file_urls(tmp_path: Path) -> None:
    image_path = tmp_path / "asset.png"
    expected = _write_png(image_path)

    data, reason = formula_ocr._safe_read_local_image_bytes(
        src=image_path.as_uri(),
        origin_path=tmp_path,
        max_bytes=10_000,
    )

    assert data == expected
    assert reason == "ok"
    assert vlm_image_caption._safe_read_local_image_bytes(
        src=image_path.as_uri(),
        origin_path=tmp_path,
        max_bytes=10_000,
    ) == expected


def test_add_image_captions_preserves_prefix_and_skips_existing_caption() -> None:
    markdown = (
        "> ![System diagram](assets/diagram.png)\n"
        "> caption: already there\n"
        "- ![Quarterly chart](assets/chart.png)\n"
    )

    result, added = image_caption.add_image_captions(markdown)

    assert added == 1
    assert result == (
        "> ![System diagram](assets/diagram.png)\n"
        "> caption: already there\n"
        "- ![Quarterly chart](assets/chart.png)\n"
        "- Image caption: Quarterly chart\n"
    )


def test_add_formula_latex_blocks_characterizes_guard_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "formula.png"
    _write_png(image_path)
    monkeypatch.setattr(formula_ocr, "_call_formula_backend", lambda **_kwargs: (" $$ x + y $$ ", "ok_json"), raising=True)

    markdown = (
        "![formula](formula.png)\n"
        "$ existing $\n"
        "![equation](formula.png)\n"
    )

    result, added, audit = formula_ocr.add_formula_latex_blocks(
        markdown,
        origin_path=tmp_path,
        api_url="http://formula",
        max_images=3,
    )

    assert added == 1
    assert result == (
        "![formula](formula.png)\n"
        "$ existing $\n"
        "![equation](formula.png)\n"
        "$$ x + y $$\n"
    )
    assert audit.formulas_added == 1
    assert audit.images_attempted == 1
    assert audit.images_succeeded == 1
    assert audit.formula_elements == [
        {
            "kind": "equation",
            "text": "x + y",
            "attributes": {
                "source_content_type": "formula_ocr",
                "source_doc_type": "formula_ocr",
                "formula_image_alt": "equation",
                "formula_image_src": "formula.png",
                "formula_backend_status": "ok_json",
            },
        }
    ]


def test_add_chart_data_blocks_characterizes_json_block_and_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "chart.png"
    image_bytes = _write_png(image_path)
    monkeypatch.setattr(settings, "CHART_TO_DATA_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "CHART_TO_DATA_API_URL", "http://chart", raising=False)
    monkeypatch.setattr(
        chart_to_data,
        "_call_chart_backend",
        lambda **_kwargs: ({"title": "Revenue", "series": [{"name": "Q1", "values": [1, 2]}], "confidence": 1.3}, "ok_json"),
        raising=True,
    )

    result, added, audit = chart_to_data.add_chart_data_blocks(
        "![Quarterly chart](chart.png)\n",
        origin_path=tmp_path,
        max_images=2,
        max_image_bytes=10_000,
    )

    expected_payload = chart_to_data.build_chart_data_v1_payload(
        {"title": "Revenue", "series": [{"name": "Q1", "values": [1, 2]}], "confidence": 1.3},
        src="chart.png",
        alt="Quarterly chart",
        image_bytes=image_bytes,
    )
    assert added == 1
    assert result == (
        "![Quarterly chart](chart.png)\n"
        "\n"
        "Chart data:\n"
        "```json\n"
        f"{chart_to_data.json.dumps(expected_payload, ensure_ascii=False, indent=2)}\n"
        "```"
    )
    assert audit.charts_added == 1
    assert audit.images_attempted == 1
    assert audit.images_succeeded == 1
    assert audit.chart_elements == [
        {
            "src": "chart.png",
            "alt": "Quarterly chart",
            "schema": chart_to_data.CHART_DATA_SCHEMA_V1,
            "chart_id": expected_payload["chart_id"],
            "cache_key": expected_payload["cache_key"],
            "backend_status": "ok_json",
        }
    ]


def test_add_image_code_blocks_characterizes_visual_fallback_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "scan.png"
    _write_png(image_path)
    monkeypatch.setattr(image_code, "decode_image_codes", lambda _image: {}, raising=True)
    monkeypatch.setattr(image_code, "infer_visual_kind_from_pixels", lambda _image: "diagram", raising=True)

    result, added, audit = image_code.add_image_code_blocks(
        "![Architecture](scan.png)\n",
        origin_path=tmp_path,
        max_images=1,
        max_image_bytes=10_000,
    )

    assert added == 0
    assert result == "![Architecture](scan.png)\n"
    assert audit.codes_added == 0
    assert audit.images_attempted == 1
    assert audit.images_succeeded == 1
    assert audit.code_elements == [
        {
            "kind": "image",
            "visual_kind": "diagram",
            "text": "Architecture",
            "attributes": {
                "source_content_type": "image_understanding",
                "source_doc_type": "image",
                "image_code_text": None,
                "image_code_values": [],
                "image_code_src": "scan.png",
                "image_code_alt": "Architecture",
                "image_visual_kind_source": "pixel",
            },
        }
    ]


def test_add_vlm_image_captions_characterizes_alt_and_filename_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "camera-shot.png"
    _write_png(image_path)
    monkeypatch.setattr(vlm_image_caption.settings, "MAX_INLINE_IMAGE_BYTES", 10_000, raising=False)
    result, added, audit = vlm_image_caption.add_vlm_image_captions(
        "![Detailed alt](camera-shot.png)\n![image](missing.png)\n![photo](camera-shot.png)\n",
        origin_path=tmp_path,
        api_url="http://caption",
        max_images=4,
        max_image_bytes=10_000,
    )

    assert added == 3
    assert result == (
        "![Detailed alt](camera-shot.png)\n"
        "Image caption: Detailed alt\n"
        "![image](missing.png)\n"
        "Image caption: image\n"
        "![photo](camera-shot.png)\n"
        "Image caption: photo\n"
    )
    assert audit.captions_added == 3
    assert audit.images_attempted == 0
    assert audit.images_succeeded == 0


def test_load_image_for_ocr_characterizes_path_then_base64_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tenant_id = "tenant-1"
    tenant_root = tmp_path / tenant_id
    tenant_root.mkdir()
    image_path = tenant_root / "page.png"
    image_bytes = _write_png(image_path)
    monkeypatch.setattr(image_understanding.settings, "UPLOAD_DIR", str(tmp_path), raising=False)

    image, should_close = image_understanding.load_image_for_ocr(
        {"doc_type_kwd": "image", "image_path": str(image_path)},
        _tenant_id=tenant_id,
    )

    assert image is not None
    assert image.size == (8, 8)
    assert should_close is True
    image.close()

    encoded = image_bytes.hex()
    monkeypatch.setattr(image_understanding, "_b64_to_bytes", lambda _value: image_bytes if _value == encoded else b"", raising=True)
    image2, should_close2 = image_understanding.load_image_for_ocr(
        {"doc_type_kwd": "image", "image_base64": encoded},
        _tenant_id=tenant_id,
    )

    assert image2 is not None
    assert image2.size == (8, 8)
    assert should_close2 is True
    image2.close()


def test_bind_ocr_lines_to_table_cells_characterizes_bound_rows_and_confidence() -> None:
    table = TableExtraction(
        columns=["A", "B"],
        rows=[["", "done"]],
        cells=[
            TableCell(row_index=1, col_index=0, text="", bbox={"left": 0, "top": 0, "right": 50, "bottom": 20}),
            TableCell(row_index=1, col_index=1, text="done", bbox={"left": 50, "top": 0, "right": 100, "bottom": 20}),
        ],
        metadata={"source": "fixture"},
    )

    result = bind_ocr_lines_to_table_cells(
        table,
        [
            {"text": "bound", "confidence": 0.8, "bbox": {"left": 5, "top": 1, "right": 45, "bottom": 19}},
            {"text": "skip", "confidence": 0.2, "bbox": {"left": 200, "top": 0, "right": 240, "bottom": 20}},
        ],
    )

    assert result.bound_cells == 1
    assert result.table.rows == [["bound", "done"]]
    assert result.metadata == {
        "applied": True,
        "bound_cells": 1,
        "ocr_lines": 2,
        "avg_confidence": 0.8,
    }


def test_decode_image_codes_characterizes_clean_ean13_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_understanding, "_decode_clean_ean13_from_pixels", lambda _image: "5901234123457", raising=True)
    fake_pyzbar = SimpleNamespace(decode=lambda _image: [])
    fake_cv2 = SimpleNamespace(QRCodeDetector=lambda: SimpleNamespace(detectAndDecode=lambda _candidate: ("", None, None)))
    monkeypatch.setitem(__import__("sys").modules, "pyzbar.pyzbar", fake_pyzbar)
    monkeypatch.setitem(__import__("sys").modules, "cv2", fake_cv2)

    payload = image_understanding.decode_image_codes(Image.new("RGB", (8, 8), color="white"))

    assert payload == {
        "visual_kind": "barcode",
        "text": "5901234123457",
        "values": ["5901234123457"],
    }
