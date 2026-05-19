from __future__ import annotations

from app.parsing.enrich.header_footer_remover import remove_repeated_header_footer_elements


def _block(block_id: str, text: str, *, page: int, y0: int, y1: int) -> dict:
    return {
        "id": block_id,
        "kind": "paragraph",
        "page": page,
        "text": text,
        "bbox": {"x0": 0, "x1": 100, "y0": y0, "y1": y1},
    }


def test_remove_repeated_header_footer_elements_removes_only_repeated_page_edges():
    elements = [
        _block("h1", "季度报告", page=1, y0=0, y1=20),
        _block("b1", "第一页正文", page=1, y0=120, y1=160),
        _block("f1", "Page 1", page=1, y0=930, y1=950),
        _block("h2", "季度报告", page=2, y0=0, y1=20),
        _block("b2", "第二页正文", page=2, y0=120, y1=160),
        _block("f2", "Page 2", page=2, y0=930, y1=950),
        _block("h3", "季度报告", page=3, y0=0, y1=20),
        _block("b3", "第三页正文", page=3, y0=120, y1=160),
        _block("f3", "Page 3", page=3, y0=930, y1=950),
    ]

    result = remove_repeated_header_footer_elements(elements)

    assert [item["id"] for item in result.elements] == ["b1", "b2", "b3"]
    assert result.changed is True
    assert result.removed_count == 6
    assert result.removed_ids == ["h1", "f1", "h2", "f2", "h3", "f3"]


def test_remove_repeated_header_footer_elements_keeps_repeated_body_text():
    elements = [
        _block("a1", "风险提示", page=1, y0=140, y1=160),
        _block("a2", "风险提示", page=2, y0=140, y1=160),
        _block("a3", "风险提示", page=3, y0=140, y1=160),
    ]

    result = remove_repeated_header_footer_elements(elements)

    assert [item["id"] for item in result.elements] == ["a1", "a2", "a3"]
    assert result.changed is False
    assert result.removed_count == 0
