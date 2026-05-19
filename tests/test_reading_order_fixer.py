from __future__ import annotations

from app.parsing.enrich.reading_order_fixer import fix_reading_order_elements


def _block(block_id: str, *, x0: int, x1: int, y0: int, y1: int) -> dict:
    return {
        "id": block_id,
        "kind": "paragraph",
        "page": 1,
        "text": block_id,
        "bbox": {"x0": x0, "x1": x1, "y0": y0, "y1": y1},
    }


def test_fix_reading_order_elements_reorders_two_column_rowwise_blocks():
    elements = [
        _block("L1", x0=0, x1=40, y0=0, y1=10),
        _block("R1", x0=60, x1=100, y0=0, y1=10),
        _block("L2", x0=0, x1=40, y0=20, y1=30),
        _block("R2", x0=60, x1=100, y0=20, y1=30),
    ]

    result = fix_reading_order_elements(elements)

    assert [item["id"] for item in result.elements] == ["L1", "L2", "R1", "R2"]
    assert result.changed is True
    assert result.column_pages == 1


def test_fix_reading_order_elements_keeps_single_column_blocks_stable():
    elements = [
        _block("A", x0=10, x1=90, y0=0, y1=10),
        _block("B", x0=12, x1=88, y0=20, y1=30),
        _block("C", x0=11, x1=86, y0=40, y1=50),
    ]

    result = fix_reading_order_elements(elements)

    assert [item["id"] for item in result.elements] == ["A", "B", "C"]
    assert result.changed is False
    assert result.column_pages == 0


def test_fix_reading_order_elements_reorders_three_column_rowwise_blocks():
    elements = [
        _block("L1", x0=0, x1=25, y0=0, y1=10),
        _block("M1", x0=40, x1=65, y0=0, y1=10),
        _block("R1", x0=80, x1=105, y0=0, y1=10),
        _block("L2", x0=0, x1=25, y0=20, y1=30),
        _block("M2", x0=40, x1=65, y0=20, y1=30),
        _block("R2", x0=80, x1=105, y0=20, y1=30),
    ]

    result = fix_reading_order_elements(elements, min_column_items=6)

    assert [item["id"] for item in result.elements] == ["L1", "L2", "M1", "M2", "R1", "R2"]
    assert result.changed is True
    assert result.column_pages == 1
