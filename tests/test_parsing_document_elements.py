from __future__ import annotations

from langchain_core.documents import Document


def test_normalize_document_elements_emits_stable_kinds_and_bbox():
    from app.parsing.utils.document_elements import normalize_document_elements  # noqa: WPS433

    docs = [
        Document(page_content="Title", metadata={"doc_type_kwd": "heading", "page": 1}),
        Document(
            page_content="印章识别：甲方公章",
            metadata={
                "doc_type_kwd": "seal",
                "page": 2,
                "seal_score": 0.97,
                "seal_bbox": {"x0": 10, "y0": 20, "x1": 40, "y1": 60},
            },
        ),
    ]

    out = normalize_document_elements(docs)

    assert [item["kind"] for item in out] == ["heading", "seal"]
    assert out[0]["page"] == 1
    assert out[1]["page"] == 2
    assert out[1]["bbox"]["x0"] == 10
    assert out[1]["confidence"] == 0.97
    assert out[1]["text"] == "印章识别：甲方公章"


def test_normalize_document_elements_uses_content_type_and_chunk_role_fallbacks():
    from app.parsing.utils.document_elements import normalize_document_elements  # noqa: WPS433

    docs = [
        Document(page_content="A | B", metadata={"content_type": "table", "page_number": 3}),
        Document(page_content="OCR text", metadata={"chunk_role": "ocr", "page": 4}),
    ]

    out = normalize_document_elements(docs)

    assert [item["kind"] for item in out] == ["table", "unknown"]
    assert out[0]["page"] == 3
    assert out[1]["page"] == 4


def test_normalize_document_elements_prefers_parser_native_element_fields():
    from app.parsing.utils.document_elements import normalize_document_elements  # noqa: WPS433

    docs = [
        Document(
            page_content="fallback text",
            metadata={
                "doc_type_kwd": "image",
                "page": 9,
                "element_kind": "table",
                "element_text": "| A | B |",
                "element_page": 2,
                "element_confidence": 0.88,
                "element_bbox": {"x0": 30, "y0": 40, "x1": 80, "y1": 90},
            },
        )
    ]

    out = normalize_document_elements(docs)

    assert out[0]["kind"] == "table"
    assert out[0]["page"] == 2
    assert out[0]["text"] == "| A | B |"
    assert out[0]["confidence"] == 0.88
    assert out[0]["bbox"] == {"x0": 30, "y0": 40, "x1": 80, "y1": 90}


def test_normalize_document_elements_strips_position_tags_from_parser_native_text():
    from app.parsing.utils.document_elements import normalize_document_elements  # noqa: WPS433

    docs = [
        Document(
            page_content="fallback text",
            metadata={
                "element_kind": "equation",
                "element_text": "E = mc^2@@2\t20\t80\t30\t90##",
                "element_page": 2,
                "element_bbox": {"x0": 20, "y0": 30, "x1": 80, "y1": 90},
            },
        )
    ]

    out = normalize_document_elements(docs)

    assert out[0]["kind"] == "equation"
    assert out[0]["text"] == "E = mc^2"


def test_normalize_document_elements_exposes_cross_page_pages_as_typed_field():
    from app.parsing.utils.document_elements import normalize_document_elements  # noqa: WPS433

    docs = [
        Document(
            page_content="| A | B |\n| --- | --- |\n| 1 | 2 |",
            metadata={
                "element_kind": "table",
                "page": 1,
                "cross_page_merged": True,
                "cross_page_merge_pages": [1, 2],
                "cross_page_merge_count": 2,
            },
        )
    ]

    out = normalize_document_elements(docs)

    assert out[0]["kind"] == "table"
    assert out[0]["page"] == 1
    assert out[0]["pages"] == [1, 2]


def test_normalize_document_elements_preserves_cross_page_table_pages_after_merge() -> None:
    from app.parsing.processors.cross_page_merge import merge_cross_page_documents  # noqa: WPS433
    from app.parsing.utils.document_elements import normalize_document_elements  # noqa: WPS433

    docs = [
        Document(
            page_content="| Region | Q1 | Q2 |\n| --- | --- | --- |\n| North | 120 | 132 |",
            metadata={
                "page": 1,
                "doc_type_kwd": "table",
                "table_columns": ["Region", "Q1", "Q2"],
                "table_header_present": True,
                "table_truncated": True,
            },
        ),
        Document(
            page_content="| Region | Q1 | Q2 |\n| --- | --- | --- |\n| South | 98 | 110 |",
            metadata={
                "page": 2,
                "doc_type_kwd": "table",
                "table_columns": ["Region", "Q1", "Q2"],
                "table_header_present": True,
                "table_continued": True,
            },
        ),
    ]

    merged = merge_cross_page_documents(docs)
    out = normalize_document_elements(merged)

    assert len(out) == 1
    assert out[0]["kind"] == "table"
    assert out[0]["page"] == 1
    assert out[0]["pages"] == [1, 2]


def test_normalize_document_elements_infers_visual_kind_for_image_elements():
    from app.parsing.utils.document_elements import normalize_document_elements  # noqa: WPS433

    docs = [
        Document(
            page_content="chart preview",
            metadata={
                "doc_type_kwd": "image",
                "page": 3,
                "element_kind": "image",
                "element_text": "Revenue growth chart for Q1",
            },
        )
    ]

    out = normalize_document_elements(docs)

    assert out[0]["kind"] == "image"
    assert out[0]["visual_kind"] == "chart"


def test_normalize_document_elements_infers_visual_kind_from_image_path() -> None:
    from app.parsing.utils.document_elements import normalize_document_elements  # noqa: WPS433

    docs = [
        Document(
            page_content="image placeholder",
            metadata={
                "doc_type_kwd": "image",
                "page": 1,
                "image_path": "/tmp/assets/customer_qrcode.png",
            },
        )
    ]

    out = normalize_document_elements(docs)

    assert out[0]["kind"] == "image"
    assert out[0]["visual_kind"] == "qr"


def test_normalize_document_elements_infers_visual_kind_from_image_url() -> None:
    from app.parsing.utils.document_elements import normalize_document_elements  # noqa: WPS433

    docs = [
        Document(
            page_content="image placeholder",
            metadata={
                "doc_type_kwd": "image",
                "page": 1,
                "image_url": "https://cdn.example.com/inventory-barcode-label.png",
            },
        )
    ]

    out = normalize_document_elements(docs)

    assert out[0]["kind"] == "image"
    assert out[0]["visual_kind"] == "barcode"


def test_normalize_document_elements_prefers_image_code_text_for_qr_and_barcode_images() -> None:
    from app.parsing.utils.document_elements import normalize_document_elements  # noqa: WPS433

    docs = [
        Document(
            page_content="Image",
            metadata={
                "doc_type_kwd": "image",
                "page": 1,
                "visual_kind": "qr",
                "image_code_text": "HELLO-QR",
            },
        ),
        Document(
            page_content="Image",
            metadata={
                "doc_type_kwd": "image",
                "page": 2,
                "visual_kind": "barcode",
                "image_code_text": "5901234123457",
            },
        ),
    ]

    out = normalize_document_elements(docs)

    assert out[0]["text"] == "HELLO-QR"
    assert out[1]["text"] == "5901234123457"
