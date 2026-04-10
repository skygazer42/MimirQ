from __future__ import annotations

from pathlib import Path

from app.parsing.parsers.docling_parser import DoclingParser


def test_docling_parser_marks_table_and_image_element_kinds(monkeypatch, tmp_path: Path) -> None:
    parser = DoclingParser(extract_images=True)

    monkeypatch.setattr(
        parser,
        "_get_parser",
        lambda: type(
            "_DummyInner",
            (),
            {
                "page_images": [],
                "page_from": 0,
            },
        )(),
        raising=False,
    )
    monkeypatch.setattr(
        DoclingParser,
        "_call_parse_method",
        lambda self, _parser, _file_path, _binary, _callback, **_kwargs: (
            [
                ("| A | B |\n| --- | --- |\n| 1 | 2 |", {"content_type": "table", "doc_type_kwd": "table"}),
                ("Figure 1", {"content_type": "image", "doc_type_kwd": "image"}),
                ("Paragraph", {"content_type": "text"}),
            ],
            [],
        ),
        raising=False,
    )

    def _fake_super_parse(self, file_path: Path, **kwargs):  # noqa: ANN001
        from langchain_core.documents import Document

        return [
            Document(
                page_content="| A | B |\n| --- | --- |\n| 1 | 2 |",
                metadata={"content_type": "table", "doc_type_kwd": "table", "positions": [(0, 10, 50, 20, 60)]},
            ),
            Document(
                page_content="Figure 1",
                metadata={"content_type": "image", "doc_type_kwd": "image", "positions": [(1, 30, 80, 40, 90)]},
            ),
            Document(page_content="Paragraph", metadata={"content_type": "text"}),
        ]

    monkeypatch.setattr("app.parsing.parsers.docling_parser.BaseAdvancedParser.parse", _fake_super_parse, raising=True)

    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake\n")

    docs = parser.parse(file_path)

    assert docs[0].metadata["element_kind"] == "table"
    assert docs[0].metadata["element_text"].startswith("| A | B |")
    assert docs[0].metadata["element_page"] == 1
    assert docs[0].metadata["element_bbox"] == {"x0": 10, "x1": 50, "y0": 20, "y1": 60}
    assert docs[0].metadata["element_attributes"]["source_content_type"] == "table"
    assert docs[0].metadata["element_attributes"]["source_doc_type"] == "table"
    assert docs[0].metadata["element_attributes"]["positions"] == [(0, 10, 50, 20, 60)]
    assert docs[1].metadata["element_kind"] == "image"
    assert docs[1].metadata["element_text"] == "Figure 1"
    assert docs[1].metadata["element_page"] == 2
    assert docs[1].metadata["element_bbox"] == {"x0": 30, "x1": 80, "y0": 40, "y1": 90}
    assert docs[1].metadata["element_attributes"]["source_content_type"] == "image"
    assert docs[1].metadata["element_attributes"]["positions"] == [(1, 30, 80, 40, 90)]
    assert docs[2].metadata["element_kind"] == "paragraph"
    assert docs[2].metadata["element_text"] == "Paragraph"
    assert docs[2].metadata["element_attributes"]["source_content_type"] == "text"


def test_docling_parser_emits_equation_docs_with_native_element_payload(monkeypatch, tmp_path: Path) -> None:
    parser = DoclingParser(extract_images=False)

    monkeypatch.setattr(parser, "_get_parser", lambda: object(), raising=False)
    monkeypatch.setattr(parser, "_check_parser_installation", lambda _parser: (True, ""), raising=False)
    monkeypatch.setattr(
        parser,
        "_call_parse_method",
        lambda **_kwargs: (
            [
                ("Body paragraph", "text", "@@1\t10\t50\t20\t60##"),
                ("E = mc^2", "equation", "@@2\t20\t80\t30\t90##"),
            ],
            [],
        ),
        raising=False,
    )

    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake\n")

    docs = parser.parse(file_path)

    paragraph_doc = docs[0]
    equation_doc = docs[1]

    assert paragraph_doc.metadata["element_kind"] == "paragraph"
    assert equation_doc.metadata["element_kind"] == "equation"
    assert equation_doc.metadata["element_text"] == "E = mc^2@@2\t20\t80\t30\t90##"
    assert equation_doc.metadata["element_page"] == 2
    assert equation_doc.metadata["element_bbox"] == {"x0": 20, "x1": 80, "y0": 30, "y1": 90}
