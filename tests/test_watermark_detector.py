from __future__ import annotations

from app.parsing.enrich.watermark_detector import remove_document_watermark_elements
from app.parsing.parsers.deepdoc_parser import DeepDocParser


class _WatermarkPdfParser:
    total_page = 3

    def __call__(self, _path: str, **_kwargs):  # noqa: ANN001
        return (
            [
                ("正文第一页", "text", "@@1\t0\t100\t120\t160##"),
                ("微信文章在线转PDF", "text", "@@1\t20\t90\t400\t430##"),
                ("正文第二页", "text", "@@2\t0\t100\t120\t160##"),
                ("微信文章在线转PDF", "text", "@@2\t20\t90\t400\t430##"),
                ("正文第三页", "text", "@@3\t0\t100\t120\t160##"),
                ("www.wechat2pdf.com", "text", "@@3\t20\t90\t400\t430##"),
            ],
            [],
        )


def test_watermark_detector_removes_repeated_pdf_export_noise() -> None:
    elements = [
        {"id": "body-1", "kind": "paragraph", "text": "正文第一页", "page": 1, "bbox": {"x0": 0, "x1": 100, "y0": 120, "y1": 160}},
        {"id": "wm-1", "kind": "paragraph", "text": "微信文章在线转PDF", "page": 1, "bbox": {"x0": 20, "x1": 90, "y0": 400, "y1": 430}},
        {"id": "body-2", "kind": "paragraph", "text": "正文第二页", "page": 2, "bbox": {"x0": 0, "x1": 100, "y0": 120, "y1": 160}},
        {"id": "wm-2", "kind": "paragraph", "text": "微信文章在线转PDF", "page": 2, "bbox": {"x0": 20, "x1": 90, "y0": 400, "y1": 430}},
    ]

    result = remove_document_watermark_elements(elements)

    assert [item["id"] for item in result.elements] == ["body-1", "body-2"]
    assert result.changed is True
    assert result.removed_count == 2
    assert result.reasons == {"pdf_export_noise": 2}


def test_watermark_detector_does_not_remove_repeated_table_headers() -> None:
    elements = [
        {"id": "h-1", "kind": "table", "text": "项目", "page": 1, "bbox": {"x0": 0, "x1": 30, "y0": 100, "y1": 120}},
        {"id": "h-2", "kind": "table", "text": "项目", "page": 2, "bbox": {"x0": 0, "x1": 30, "y0": 100, "y1": 120}},
        {"id": "p-1", "kind": "paragraph", "text": "项目背景", "page": 1, "bbox": {"x0": 0, "x1": 80, "y0": 200, "y1": 240}},
        {"id": "p-2", "kind": "paragraph", "text": "项目预算", "page": 2, "bbox": {"x0": 0, "x1": 80, "y0": 200, "y1": 240}},
    ]

    result = remove_document_watermark_elements(elements)

    assert result.changed is False
    assert [item["id"] for item in result.elements] == ["h-1", "h-2", "p-1", "p-2"]


def test_deepdoc_parser_removes_watermark_noise_before_merging(tmp_path) -> None:  # noqa: ANN001
    parser = DeepDocParser()
    parser._pdf_parser = _WatermarkPdfParser()

    docs = parser.parse(tmp_path / "watermark.pdf")

    assert docs[0].page_content.split("\n\n") == [
        "正文第一页@@1\t0\t100\t120\t160##",
        "正文第二页@@2\t0\t100\t120\t160##",
        "正文第三页@@3\t0\t100\t120\t160##",
    ]
    assert docs[0].metadata["watermark_removal"]["removed_count"] == 3
    assert docs[0].metadata["watermark_removal"]["reasons"] == {"pdf_export_noise": 3}
