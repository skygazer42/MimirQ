from langchain_core.documents import Document

from app.parsing.subprocess_worker import _serialize_documents
from app.parsing.utils.document_elements import normalize_document_elements


def test_subprocess_roundtrip_keeps_an_explicit_empty_document_id() -> None:
    original = Document(page_content="text", metadata={"count": 0, "enabled": False}, id="")

    payload = _serialize_documents([original])
    restored = Document(**payload[0])

    assert restored.id == ""
    assert restored.page_content == "text"
    assert restored.metadata == {"count": 0, "enabled": False}


def test_normalized_empty_element_keeps_actual_text_and_attribute_values() -> None:
    elements = normalize_document_elements(
        [
            Document(
                page_content="",
                metadata={"element_kind": "image", "element_attributes": {"count": 0, "enabled": False}},
            )
        ]
    )

    assert len(elements) == 1
    assert elements[0]["text"] == ""
    assert elements[0]["attributes"] == {"count": 0, "enabled": False}


def test_normalized_element_keeps_its_actual_empty_attribute_map() -> None:
    elements = normalize_document_elements([Document(page_content="text", metadata={"element_kind": "paragraph"})])

    assert elements[0]["attributes"] == {}


def test_docling_hints_preserve_raw_source_metadata() -> None:
    from app.parsing.parsers.docling_parser import _apply_element_hints

    raw = {"content_type": "", "doc_type_kwd": False}

    hinted = _apply_element_hints(raw, text="text")

    assert hinted["element_kind"] == "paragraph"
    assert hinted["element_attributes"]["source_content_type"] == ""
    assert hinted["element_attributes"]["source_doc_type"] is False
    assert raw == {"content_type": "", "doc_type_kwd": False}
