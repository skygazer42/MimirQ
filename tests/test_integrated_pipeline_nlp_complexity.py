from app.rag.ingestion.chunking.utils import chunk_records, section_merging, section_structure
from app.rag.ingestion.parsing.utils import tokenizer


def test_attach_media_context_reorders_chunks_and_refreshes_tokens(
    monkeypatch,
) -> None:
    monkeypatch.setattr(chunk_records, "num_tokens_from_string", lambda text: len(text))
    monkeypatch.setattr(tokenizer, "tokenize", lambda text: f"TK:{text}")
    monkeypatch.setattr(
        tokenizer,
        "fine_grained_tokenize",
        lambda text: f"FG:{text}",
    )
    chunks = [
        {"text": "omega", "page_num_int": [1], "top_int": [10], "position_int": [(1, 0, 10, 10, 10)]},
        {
            "doc_type_kwd": "table",
            "content_with_weight": "TABLE",
            "page_num_int": [1],
            "top_int": [5],
            "position_int": [(1, 0, 10, 5, 10)],
            "content_ltks": "old",
            "content_sm_ltks": "oldsm",
        },
        {"text": "alpha", "page_num_int": [1], "top_int": [0], "position_int": [(1, 0, 10, 0, 10)]},
    ]

    result = chunk_records.attach_media_context(chunks, table_context_size=100)

    assert [chunk.get("text", chunk.get("content_with_weight")) for chunk in result] == [
        "alpha",
        "alpha\nTABLE\nomega",
        "omega",
    ]
    assert result[1]["content_ltks"] == "TK:alpha\nTABLE\nomega"
    assert result[1]["content_sm_ltks"] == "FG:TK:alpha\nTABLE\nomega"


def test_remove_contents_table_drops_detected_toc_block() -> None:
    sections = ["目录", "第一章@@1", "第一章 绪论", "第二章 方法", "正文"]

    section_structure.remove_contents_table(sections)

    assert sections == ["第一章 绪论", "第二章 方法", "正文"]


def test_title_merges_keep_existing_grouping_behavior() -> None:
    sections = [("# Title", "head"), ("body1", "text"), ("## Sub", "head"), ("body2", "text")]

    assert section_structure.tree_merge(4, sections, 1) == ["# Title\nbody1\n## Sub\nbody2"]
    assert section_structure.hierarchical_merge(4, sections, 2) == [
        [],
        ["# Title", "body1"],
        ["# Title", "## Sub", "body2"],
    ]


def test_custom_delimiter_merges_split_chunks_without_parser_roundtrip(monkeypatch) -> None:
    monkeypatch.setattr(section_merging, "num_tokens_from_string", len)
    sections = [("alpha<CUT>beta", "@@1")]

    assert section_merging.naive_merge(sections, delimiter="`<CUT>`") == ["\nalpha", "\nbeta"]
    assert section_merging.naive_merge_with_images(sections, ["img1"], delimiter="`<CUT>`") == (
        ["\nalpha", "\nbeta"],
        ["img1", "img1"],
    )
    assert section_merging.naive_merge_docx([("alpha<CUT>beta", "img1")], delimiter="`<CUT>`") == (
        ["\nalpha", "\nbeta"],
        ["img1", "img1"],
    )
