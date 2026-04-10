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
