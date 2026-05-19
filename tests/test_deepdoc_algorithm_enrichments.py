from __future__ import annotations

from PIL import Image, ImageDraw

from app.parsing.enrich.table_cell_schema import TableCell, TableExtraction


def test_table_rotation_selects_best_ocr_confidence() -> None:
    from app.parsing.enrich.table_image_algorithms import select_table_rotation

    image = Image.new("RGB", (40, 20), "white")

    def score(rotated: Image.Image) -> float:
        return 0.95 if rotated.size == (20, 40) else 0.35

    result = select_table_rotation(image, confidence_scorer=score)

    assert result.angle == 90
    assert result.confidence == 0.95
    assert result.candidates[90] == 0.95


def test_cell_ocr_binding_uses_cell_overlap() -> None:
    from app.parsing.enrich.table_image_algorithms import bind_ocr_lines_to_table_cells

    table = TableExtraction(
        columns=["Name", "Value"],
        rows=[["", ""]],
        cells=[
            TableCell(row_index=0, col_index=0, text="Name", is_header=True, bbox={"left": 0, "top": 0, "right": 50, "bottom": 20}),
            TableCell(row_index=0, col_index=1, text="Value", is_header=True, bbox={"left": 50, "top": 0, "right": 100, "bottom": 20}),
            TableCell(row_index=1, col_index=0, text="", bbox={"left": 0, "top": 20, "right": 50, "bottom": 40}),
            TableCell(row_index=1, col_index=1, text="", bbox={"left": 50, "top": 20, "right": 100, "bottom": 40}),
        ],
    )

    result = bind_ocr_lines_to_table_cells(
        table,
        [
            {"text": "alpha", "confidence": 0.91, "bbox": {"left": 4, "top": 24, "right": 45, "bottom": 35}},
            {"text": "42", "confidence": 0.88, "bbox": {"left": 58, "top": 23, "right": 80, "bottom": 35}},
        ],
    )

    assert result.table.rows == [["alpha", "42"]]
    assert result.bound_cells == 2
    assert result.metadata["applied"] is True


def test_classify_wired_and_wireless_table_images() -> None:
    from app.parsing.enrich.table_image_algorithms import classify_table_grid_type

    wired = Image.new("RGB", (160, 100), "white")
    draw = ImageDraw.Draw(wired)
    for x in (10, 60, 110, 150):
        draw.line((x, 10, x, 90), fill="black", width=2)
    for y in (10, 40, 70, 90):
        draw.line((10, y, 150, y), fill="black", width=2)

    wireless = Image.new("RGB", (160, 100), "white")
    draw = ImageDraw.Draw(wireless)
    draw.text((15, 15), "Name   Value", fill="black")
    draw.text((15, 45), "alpha  42", fill="black")

    assert classify_table_grid_type(wired).table_type == "wired"
    assert classify_table_grid_type(wireless).table_type == "wireless"


def test_formula_and_chart_regions_are_detected_from_blocks() -> None:
    from app.parsing.enrich.document_region_algorithms import detect_chart_regions, detect_formula_regions

    elements = [
        {"id": "eq1", "kind": "equation", "text": "E = mc^2", "page": 1, "bbox": {"x0": 1, "x1": 2, "y0": 3, "y1": 4}},
        {"id": "fig1", "kind": "image", "text": "图表 1：收入趋势图", "page": 2, "bbox": {"x0": 10, "x1": 80, "y0": 20, "y1": 60}},
    ]

    formulas = detect_formula_regions(elements)
    charts = detect_chart_regions(elements)

    assert formulas["count"] == 1
    assert formulas["regions"][0]["source_element_id"] == "eq1"
    assert charts["count"] == 1
    assert charts["regions"][0]["region_type"] == "chart"


def test_document_preprocess_profile_reports_orientation_and_skew() -> None:
    from app.parsing.enrich.document_region_algorithms import profile_document_image

    image = Image.new("RGB", (80, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.line((20, 30, 60, 30), fill="black", width=2)
    draw.line((20, 60, 60, 60), fill="black", width=2)

    profile = profile_document_image(image)

    assert profile["orientation"]["angle"] == 0
    assert profile["textline_orientation"]["angle"] == 0
    assert profile["unwarp"]["needed"] is False


def test_project_rapidocr_kwargs_use_huggingface_onnx_manifest() -> None:
    from app.parsing.enrich.table_image_algorithms import _project_rapidocr_kwargs

    kwargs = _project_rapidocr_kwargs()

    assert kwargs["det_model_path"].endswith("detection/v5/det.onnx")
    assert kwargs["rec_model_path"].endswith("languages/chinese/rec.onnx")
    assert kwargs["rec_keys_path"].endswith("languages/chinese/dict.txt")
