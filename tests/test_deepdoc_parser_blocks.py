from __future__ import annotations

from PIL import Image

from app.parsing.enrich.table_image_algorithms import TableGridTypeResult, TableRotationResult
from app.parsing.enrich.table_structure_adapter import TableStructureDetection
from app.parsing.parsers.deepdoc_parser import DeepDocParser
from app.parsing.utils.document_elements import normalize_document_elements


class _StructuredPdfParser:
    total_page = 2

    def __call__(self, _path: str, **_kwargs):  # noqa: ANN001
        return (
            [
                ("合同标题", "heading", "@@1\t10\t100\t20\t40##"),
                ("正文第一段", "text", "@@1\t12\t98\t50\t70##"),
                ("E = mc^2", "equation", "@@2\t20\t80\t30\t90##"),
                ("跨页段落", "text", "@@1-2\t5\t90\t10\t20##"),
            ],
            [(object(), "图 1 系统架构@@2\t30\t120\t100\t180##")],
        )


class _TwoColumnPdfParser:
    total_page = 1

    def __call__(self, _path: str, **_kwargs):  # noqa: ANN001
        return (
            [
                ("L1", "text", "@@1\t0\t40\t0\t10##"),
                ("R1", "text", "@@1\t60\t100\t0\t10##"),
                ("L2", "text", "@@1\t0\t40\t20\t30##"),
                ("R2", "text", "@@1\t60\t100\t20\t30##"),
            ],
            [],
        )


class _HeaderFooterPdfParser:
    total_page = 3

    def __call__(self, _path: str, **_kwargs):  # noqa: ANN001
        return (
            [
                ("季度报告", "text", "@@1\t0\t100\t0\t20##"),
                ("第一页正文", "text", "@@1\t0\t100\t120\t160##"),
                ("Page 1", "text", "@@1\t0\t100\t930\t950##"),
                ("季度报告", "text", "@@2\t0\t100\t0\t20##"),
                ("第二页正文", "text", "@@2\t0\t100\t120\t160##"),
                ("Page 2", "text", "@@2\t0\t100\t930\t950##"),
                ("季度报告", "text", "@@3\t0\t100\t0\t20##"),
                ("第三页正文", "text", "@@3\t0\t100\t120\t160##"),
                ("Page 3", "text", "@@3\t0\t100\t930\t950##"),
            ],
            [],
        )


class _TableMediaPdfParser:
    total_page = 1

    def __call__(self, _path: str, **_kwargs):  # noqa: ANN001
        return (
            ["表格说明@@1\t0\t100\t0\t20##"],
            [
                (
                    object(),
                    "\n".join(
                        [
                            "Table 1@@1\t10\t100\t100\t180##",
                            "| Name | Value |",
                            "| --- | --- |",
                            "| alpha | 1 |",
                            "| beta | 2 |",
                        ]
                    ),
                )
            ],
        )


class _TableMediaImagePdfParser:
    total_page = 1

    def __call__(self, _path: str, **_kwargs):  # noqa: ANN001
        return (
            ["表格说明@@1\t0\t100\t0\t20##"],
            [
                (
                    Image.new("RGB", (80, 40), "white"),
                    "\n".join(
                        [
                            "Table 1@@1\t10\t100\t100\t180##",
                            "| Name | Value |",
                            "| --- | --- |",
                            "| alpha | 1 |",
                        ]
                    ),
                )
            ],
        )


class _TableImageOnlyPdfParser:
    total_page = 1

    def __call__(self, _path: str, **_kwargs):  # noqa: ANN001
        return (
            ["表格说明@@1\t0\t100\t0\t20##"],
            [
                (
                    Image.new("RGB", (100, 40), "white"),
                    "scanned table@@1\t10\t100\t100\t180##",
                )
            ],
        )


class _ConfidencePdfParser:
    total_page = 1

    def __call__(self, _path: str, **_kwargs):  # noqa: ANN001
        return (
            [
                ("低置信OCR", "text", "@@1\t0\t100\t0\t20##", {"confidence": 0.52}),
                ("高置信OCR", "text", "@@1\t0\t100\t30\t50##", {"confidence": 0.94}),
            ],
            [],
        )


class _CrossPageTablePdfParser:
    total_page = 2

    def __call__(self, _path: str, **_kwargs):  # noqa: ANN001
        return (
            ["表格说明@@1\t0\t100\t0\t20##"],
            [
                (
                    object(),
                    "\n".join(
                        [
                            "Table 1@@1\t10\t100\t780\t950##",
                            "| Name | Value |",
                            "| --- | --- |",
                            "| alpha | 1 |",
                        ]
                    ),
                ),
                (
                    object(),
                    "\n".join(
                        [
                            "Table 1 continued@@2\t10\t100\t20\t160##",
                            "| Name | Value |",
                            "| --- | --- |",
                            "| beta | 2 |",
                        ]
                    ),
                ),
            ],
        )


def test_deepdoc_parser_exposes_pdf_sections_as_structured_block_graph(tmp_path):
    parser = DeepDocParser()
    parser._pdf_parser = _StructuredPdfParser()

    docs = parser.parse(tmp_path / "contract.pdf")

    runtime = docs[0].metadata["small_model_runtime"]
    assert runtime["layout"]["model_id"] == "deepdoc_layout_onnx"
    assert runtime["layout"]["available"] is True
    assert runtime["table_structure"]["model_id"] == "deepdoc_tsr_onnx"
    assert runtime["table_structure"]["available"] is True

    assert docs[0].metadata["element_kind"] == "paragraph"
    assert docs[0].metadata["element_text"].startswith("合同标题@@1")
    blocks = docs[0].metadata["derived_elements"]
    assert [item["kind"] for item in blocks] == ["heading", "paragraph", "equation", "paragraph"]
    assert blocks[0]["id"] == "deepdoc:section:0"
    assert blocks[0]["page"] == 1
    assert blocks[0]["bbox"] == {"x0": 10, "x1": 100, "y0": 20, "y1": 40}
    assert blocks[0]["source_backend"] == "deepdoc"
    assert blocks[0]["source_element_id"] == "section:0"
    assert blocks[0]["attributes"]["position_tag"] == "@@1\t10\t100\t20\t40##"
    assert blocks[3]["pages"] == [1, 2]
    assert docs[0].metadata["formula_regions"]["count"] == 1
    assert docs[0].metadata["formula_regions"]["regions"][0]["source_element_id"] == "deepdoc:section:2"

    elements = normalize_document_elements(docs)
    section_elements = [item for item in elements if str(item["id"]).startswith("deepdoc:section:")]
    assert section_elements[2]["kind"] == "equation"
    assert section_elements[2]["text"] == "E = mc^2"
    assert section_elements[2]["source_backend"] == "deepdoc"
    assert section_elements[2]["source_element_id"] == "section:2"
    assert section_elements[3]["pages"] == [1, 2]


def test_deepdoc_parser_marks_media_docs_with_native_block_metadata(tmp_path):
    parser = DeepDocParser()
    parser._pdf_parser = _StructuredPdfParser()

    docs = parser.parse(tmp_path / "contract.pdf")
    media_doc = docs[1]

    assert media_doc.metadata["element_id"] == "deepdoc:media:0"
    assert media_doc.metadata["element_kind"] == "image"
    assert media_doc.metadata["element_text"] == "图 1 系统架构@@2\t30\t120\t100\t180##"
    assert media_doc.metadata["element_page"] == 2
    assert media_doc.metadata["element_bbox"] == {"x0": 30, "x1": 120, "y0": 100, "y1": 180}
    assert media_doc.metadata["source_backend"] == "deepdoc"
    assert media_doc.metadata["source_element_id"] == "media:0"

    elements = normalize_document_elements([media_doc])
    assert elements[0]["kind"] == "image"
    assert elements[0]["text"] == "图 1 系统架构"
    assert elements[0]["source_backend"] == "deepdoc"
    assert elements[0]["source_element_id"] == "media:0"


def test_deepdoc_parser_applies_reading_order_fix_to_merged_markdown(tmp_path):
    parser = DeepDocParser()
    parser._pdf_parser = _TwoColumnPdfParser()

    docs = parser.parse(tmp_path / "two-column.pdf")

    assert docs[0].page_content.split("\n\n") == [
        "L1@@1\t0\t40\t0\t10##",
        "L2@@1\t0\t40\t20\t30##",
        "R1@@1\t60\t100\t0\t10##",
        "R2@@1\t60\t100\t20\t30##",
    ]
    assert [item["source_element_id"] for item in docs[0].metadata["derived_elements"]] == [
        "section:0",
        "section:2",
        "section:1",
        "section:3",
    ]
    assert docs[0].metadata["reading_order_fix"]["changed"] is True


def test_deepdoc_parser_removes_repeated_header_footer_before_merging(tmp_path):
    parser = DeepDocParser()
    parser._pdf_parser = _HeaderFooterPdfParser()

    docs = parser.parse(tmp_path / "header-footer.pdf")

    assert docs[0].page_content.split("\n\n") == [
        "第一页正文@@1\t0\t100\t120\t160##",
        "第二页正文@@2\t0\t100\t120\t160##",
        "第三页正文@@3\t0\t100\t120\t160##",
    ]
    assert [item["source_element_id"] for item in docs[0].metadata["derived_elements"]] == [
        "section:1",
        "section:4",
        "section:7",
    ]
    assert docs[0].metadata["header_footer_removal"]["removed_count"] == 6


def test_deepdoc_parser_marks_markdown_table_media_for_tag_sidecar(tmp_path):
    parser = DeepDocParser()
    parser._pdf_parser = _TableMediaPdfParser()

    docs = parser.parse(tmp_path / "table.pdf")
    table_doc = docs[1]

    assert table_doc.metadata["small_model_runtime"]["table_structure"]["model_id"] == "deepdoc_tsr_onnx"
    assert table_doc.metadata["element_id"] == "deepdoc:media:0"
    assert table_doc.metadata["content_type"] == "table"
    assert table_doc.metadata["doc_type_kwd"] == "table"
    assert table_doc.metadata["element_kind"] == "table"
    assert table_doc.metadata["element_page"] == 1
    assert table_doc.metadata["element_bbox"] == {"x0": 10, "x1": 100, "y0": 100, "y1": 180}
    assert table_doc.metadata["table_columns"] == ["Name", "Value"]
    assert table_doc.metadata["table_shape"] == {"rows": 2, "columns": 2}
    assert table_doc.metadata["table_extraction"]["row_count"] == 2
    assert table_doc.metadata["table_extraction"]["col_count"] == 2
    assert table_doc.metadata["table_outputs"]["csv"].splitlines() == ["Name,Value", "alpha,1", "beta,2"]
    assert table_doc.metadata["element_attributes"]["source_content_type"] == "table"
    assert "| alpha | 1 |" in table_doc.page_content


def test_deepdoc_parser_adds_tatr_onnx_table_structure_metadata(tmp_path, monkeypatch):
    parser = DeepDocParser()
    parser._pdf_parser = _TableMediaImagePdfParser()

    def fake_predict(*_args, **_kwargs):
        return [TableStructureDetection(label="table row", score=0.91, bbox={"left": 1, "top": 2, "right": 3, "bottom": 4})]

    monkeypatch.setattr("app.parsing.parsers.deepdoc_parser.predict_table_structure_detections", fake_predict)
    monkeypatch.setattr(
        "app.parsing.parsers.deepdoc_parser.select_table_rotation",
        lambda *_args, **_kwargs: TableRotationResult(angle=90, confidence=0.93, candidates={0: 0.2, 90: 0.93}),
    )
    monkeypatch.setattr(
        "app.parsing.parsers.deepdoc_parser.classify_table_grid_type",
        lambda *_args, **_kwargs: TableGridTypeResult(
            table_type="wired",
            vertical_lines=4,
            horizontal_lines=3,
            line_density=0.12,
        ),
    )
    monkeypatch.setattr(
        "app.parsing.parsers.deepdoc_parser.extract_ocr_lines_from_image",
        lambda *_args, **_kwargs: [{"text": "alpha", "confidence": 0.91, "bbox": {"left": 0, "top": 20, "right": 40, "bottom": 40}}],
    )

    docs = parser.parse(tmp_path / "table-image.pdf")
    table_doc = docs[1]

    assert table_doc.metadata["table_structure_model"]["model"]["model_id"] == "tatr_v1_1_all_onnx"
    assert table_doc.metadata["table_structure_model"]["detection_count"] == 1
    assert table_doc.metadata["table_structure_model"]["detections"][0]["label"] == "table row"
    assert table_doc.metadata["table_image_algorithms"]["rotation"]["angle"] == 90
    assert table_doc.metadata["table_image_algorithms"]["grid"]["table_type"] == "wired"
    assert table_doc.metadata["table_image_algorithms"]["cell_ocr_binding"]["ocr_lines"] == 1
    assert table_doc.metadata["document_image_profile"]["schema"] == "mimirq.document_image_profile.v1"


def test_deepdoc_parser_turns_tatr_row_column_detections_into_table_doc(tmp_path, monkeypatch):
    parser = DeepDocParser()
    parser._pdf_parser = _TableImageOnlyPdfParser()

    def fake_predict(*_args, **_kwargs):
        return [
            TableStructureDetection(label="table row", score=0.93, bbox={"left": 0, "top": 0, "right": 100, "bottom": 20}),
            TableStructureDetection(label="table row", score=0.91, bbox={"left": 0, "top": 20, "right": 100, "bottom": 40}),
            TableStructureDetection(label="table column", score=0.9, bbox={"left": 0, "top": 0, "right": 50, "bottom": 40}),
            TableStructureDetection(label="table column", score=0.88, bbox={"left": 50, "top": 0, "right": 100, "bottom": 40}),
        ]

    monkeypatch.setattr("app.parsing.parsers.deepdoc_parser.predict_table_structure_detections", fake_predict)
    monkeypatch.setattr(
        "app.parsing.parsers.deepdoc_parser.extract_ocr_lines_from_image",
        lambda *_args, **_kwargs: [{"text": "42", "confidence": 0.91, "bbox": {"left": 52, "top": 21, "right": 95, "bottom": 39}}],
    )

    docs = parser.parse(tmp_path / "table-image-only.pdf")
    table_doc = docs[1]

    assert table_doc.metadata["content_type"] == "table"
    assert table_doc.metadata["table_extraction"]["metadata"]["source"] == "table_structure_detections"
    assert table_doc.metadata["table_image_algorithms"]["cell_ocr_binding"]["bound_cells"] == 1
    assert "42" in table_doc.metadata["table_outputs"]["markdown"]


def test_deepdoc_parser_preserves_block_confidence_for_ocr_quality(tmp_path):
    parser = DeepDocParser()
    parser._pdf_parser = _ConfidencePdfParser()

    docs = parser.parse(tmp_path / "confidence.pdf")

    elements = docs[0].metadata["derived_elements"]
    assert elements[0]["confidence"] == 0.52
    assert elements[1]["confidence"] == 0.94


def test_deepdoc_parser_links_cross_page_table_media(tmp_path):
    parser = DeepDocParser()
    parser._pdf_parser = _CrossPageTablePdfParser()

    docs = parser.parse(tmp_path / "cross-page-table.pdf")

    table_docs = [doc for doc in docs if doc.metadata.get("content_type") == "table"]
    assert len(table_docs) == 1
    assert table_docs[0].metadata["cross_page_table_link"]["pages"] == [1, 2]
    assert table_docs[0].metadata["table_extraction"]["row_count"] == 2
    assert "| beta | 2 |" in table_docs[0].page_content
