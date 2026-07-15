from app.parsing.factory import ParserFactory


def test_colpali_pdf_backend_is_routable(tmp_path):
    pdf_path = tmp_path / "visual.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    documents, resolved_backend = ParserFactory().parse(
        pdf_path,
        parser_backend="colpali",
        allow_fallback=False,
    )

    assert resolved_backend == "colpali"
    assert len(documents) == 1
    assert documents[0].metadata["parser_backend"] == "colpali"
    assert documents[0].page_content == "[visual-document](visual.pdf)\n"
