from types import SimpleNamespace


def test_runtime_metadata_reads_pdf_page_count(tmp_path):
    from pypdf import PdfWriter

    from app.services.document_runtime_metadata import build_runtime_document_metadata

    pdf_path = tmp_path / "sample.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    document = SimpleNamespace(
        doc_metadata={"page_count": 0},
        file_path=str(pdf_path),
        file_type="pdf",
    )

    metadata = build_runtime_document_metadata(document)

    assert metadata["page_count"] == 2
    assert metadata["page_count_source"] == "source_pdf"


def test_runtime_metadata_extracts_image_and_table_counts_from_elements():
    from app.services.document_runtime_metadata import build_runtime_document_metadata

    document = SimpleNamespace(
        doc_metadata={
            "elements": [
                {
                    "kind": "paragraph",
                    "text": "before ![](/api/v1/documents/image/abc) <table><tr></tr></table>",
                },
                {"kind": "image", "text": ""},
            ],
            "image_count": 0,
            "table_count": 0,
        },
        file_path="",
        file_type="md",
    )

    metadata = build_runtime_document_metadata(document)

    assert metadata["image_count"] == 2
    assert metadata["image_count_source"] == "elements"
    assert metadata["table_count"] == 1
    assert metadata["table_count_source"] == "elements"


def test_runtime_metadata_does_not_fake_missing_pdf_page_count():
    from app.services.document_runtime_metadata import build_runtime_document_metadata

    document = SimpleNamespace(
        doc_metadata={"page_count": 0},
        file_path="/does/not/exist.pdf",
        file_type="pdf",
    )

    metadata = build_runtime_document_metadata(document)

    assert metadata["page_count"] == 0
    assert "page_count_source" not in metadata
