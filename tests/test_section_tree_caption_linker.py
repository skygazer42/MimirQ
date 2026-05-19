from __future__ import annotations

from app.parsing.enrich.caption_linker import find_nearest_caption
from app.parsing.enrich.section_tree import build_section_tree
from app.parsing.parsers.deepdoc_parser import DeepDocParser


def test_build_section_tree_supports_chinese_and_numeric_headings() -> None:
    elements = [
        {"id": "h1", "kind": "heading", "text": "一、项目背景", "page": 1},
        {"id": "h2", "kind": "heading", "text": "（一）业务现状", "page": 1},
        {"id": "h3", "kind": "heading", "text": "1.1 数据来源", "page": 2},
        {"id": "p1", "kind": "paragraph", "text": "正文", "page": 2},
    ]

    tree = build_section_tree(elements)

    assert [node["id"] for node in tree] == ["h1", "h2", "h3"]
    assert [node["level"] for node in tree] == [1, 2, 2]
    assert tree[0]["parent_id"] is None
    assert tree[1]["parent_id"] == "h1"
    assert tree[2]["parent_id"] == "h1"


def test_build_section_tree_supports_english_chapter_and_section_headings() -> None:
    elements = [
        {"id": "c1", "kind": "heading", "text": "Chapter 1 Overview", "page": 1},
        {"id": "s1", "kind": "heading", "text": "Section 1.1 Scope", "page": 1},
    ]

    tree = build_section_tree(elements)

    assert [node["level"] for node in tree] == [1, 2]
    assert tree[1]["parent_id"] == "c1"


def test_find_nearest_caption_links_same_page_figure_caption() -> None:
    elements = [
        {
            "id": "cap-1",
            "kind": "paragraph",
            "text": "图 1 系统架构",
            "page": 2,
            "bbox": {"x0": 30, "x1": 120, "y0": 82, "y1": 96},
        },
        {
            "id": "p-1",
            "kind": "paragraph",
            "text": "普通正文",
            "page": 2,
            "bbox": {"x0": 10, "x1": 180, "y0": 250, "y1": 280},
        },
    ]

    caption = find_nearest_caption(
        elements,
        media_kind="image",
        page=2,
        bbox={"x0": 30, "x1": 120, "y0": 100, "y1": 180},
    )

    assert caption is not None
    assert caption["id"] == "cap-1"
    assert caption["text"] == "图 1 系统架构"


class _CaptionPdfParser:
    total_page = 2

    def __call__(self, _path: str, **_kwargs):  # noqa: ANN001
        return (
            [
                ("一、项目背景", "heading", "@@1\t10\t100\t20\t40##"),
                ("（一）业务现状", "heading", "@@1\t12\t100\t50\t70##"),
                ("图 1 系统架构", "text", "@@2\t30\t120\t82\t96##"),
                ("正文说明", "text", "@@2\t10\t160\t200\t230##"),
            ],
            [(object(), "架构图@@2\t30\t120\t100\t180##")],
        )


def test_deepdoc_parser_persists_section_tree_and_media_caption(tmp_path) -> None:  # noqa: ANN001
    parser = DeepDocParser()
    parser._pdf_parser = _CaptionPdfParser()

    docs = parser.parse(tmp_path / "caption.pdf")

    section_tree = docs[0].metadata["section_tree"]
    assert [node["text"] for node in section_tree] == ["一、项目背景", "（一）业务现状"]
    assert section_tree[1]["parent_id"] == section_tree[0]["id"]

    media = docs[1]
    assert media.metadata["caption"]["text"] == "图 1 系统架构"
    assert media.metadata["caption"]["source_element_id"] == "section:2"
    assert media.metadata["element_attributes"]["caption_text"] == "图 1 系统架构"
