from __future__ import annotations

from app.parsing.enrich.table_structure_adapter import (
    TableStructureDetection,
    table_extraction_from_structure_detections,
    table_extraction_from_text_grid,
)


def test_table_extraction_from_text_grid_preserves_geometry_and_confidence() -> None:
    extraction = table_extraction_from_text_grid(
        columns=["项目", "金额"],
        rows=[["A", "10"], ["B", "20"]],
        page=3,
        bbox={"x0": 12, "x1": 220, "y0": 80, "y1": 180},
        source_element_id="media:2",
        detections=[
            TableStructureDetection(label="table row", score=0.91, bbox={"x0": 12, "x1": 220, "y0": 110, "y1": 140}),
            TableStructureDetection(label="table column", score=0.87, bbox={"x0": 12, "x1": 110, "y0": 80, "y1": 180}),
        ],
    )

    assert extraction.columns == ["项目", "金额"]
    assert extraction.rows == [["A", "10"], ["B", "20"]]
    assert extraction.confidence == 0.89
    meta = extraction.to_metadata()
    assert meta["source_page"] == 3
    assert meta["source_bbox"] == {"x0": 12, "x1": 220, "y0": 80, "y1": 180}
    assert meta["metadata"]["structure_detections"][0]["label"] == "table row"


def test_table_structure_adapter_builds_empty_cells_from_row_column_detections() -> None:
    table = table_extraction_from_structure_detections(
        [
            TableStructureDetection(label="table row", score=0.9, bbox={"left": 0, "top": 0, "right": 100, "bottom": 20}),
            TableStructureDetection(label="table row", score=0.8, bbox={"left": 0, "top": 20, "right": 100, "bottom": 40}),
            TableStructureDetection(label="table column", score=0.9, bbox={"left": 0, "top": 0, "right": 50, "bottom": 40}),
            TableStructureDetection(label="table column", score=0.85, bbox={"left": 50, "top": 0, "right": 100, "bottom": 40}),
        ],
        image_size=(100, 40),
        page=3,
        source_element_id="media:1",
    )

    assert table is not None
    assert table.row_count == 1
    assert table.col_count == 2
    assert table.page == 3
    assert table.cells[0].bbox == {"left": 0.0, "top": 0.0, "right": 50.0, "bottom": 20.0}
    assert table.metadata["source"] == "table_structure_detections"
