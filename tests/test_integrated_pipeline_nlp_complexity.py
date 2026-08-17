from app.third_party.integrated_pipeline import nlp
from app.third_party.integrated_pipeline.nlp import rag_tokenizer


def test_has_qbullet_returns_match_and_index_for_question_pattern() -> None:
    box = {"text": "QUESTION TWO?", "x0": 10, "top": 50, "layout_type": "text"}
    last_box = {"text": "intro", "x0": 10, "top": 20}

    match, index = nlp.has_qbullet(
        r"QUESTION (ONE|TWO|THREE)",
        box,
        last_box,
        last_index=1,
        last_bull=True,
        bull_x0_list=[],
    )

    assert match is not None
    assert match.group(1) == "TWO"
    assert index == 2


def test_attach_media_context_reorders_chunks_and_refreshes_tokens(
    monkeypatch,
) -> None:
    monkeypatch.setattr(nlp, "num_tokens_from_string", lambda text: len(text))
    monkeypatch.setattr(rag_tokenizer, "tokenize", lambda text: f"TK:{text}")
    monkeypatch.setattr(
        rag_tokenizer,
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

    result = nlp.attach_media_context(chunks, table_context_size=100)

    assert [chunk.get("text", chunk.get("content_with_weight")) for chunk in result] == [
        "alpha",
        "alpha\nTABLE\nomega",
        "omega",
    ]
    assert result[1]["content_ltks"] == "TK:alpha\nTABLE\nomega"
    assert result[1]["content_sm_ltks"] == "FG:TK:alpha\nTABLE\nomega"


def test_remove_contents_table_drops_detected_toc_block() -> None:
    sections = ["目录", "第一章@@1", "第一章 绪论", "第二章 方法", "正文"]

    nlp.remove_contents_table(sections)

    assert sections == ["第一章 绪论", "第二章 方法", "正文"]


def test_title_merges_keep_existing_grouping_behavior() -> None:
    sections = [("# Title", "head"), ("body1", "text"), ("## Sub", "head"), ("body2", "text")]

    assert nlp.tree_merge(4, sections, 1) == ["# Title\nbody1\n## Sub\nbody2"]
    assert nlp.hierarchical_merge(4, sections, 2) == [
        [],
        ["# Title", "body1"],
        ["# Title", "## Sub", "body2"],
    ]


def test_custom_delimiter_merges_split_chunks_without_parser_roundtrip() -> None:
    sections = [("alpha<CUT>beta", "@@1")]

    assert nlp.naive_merge(sections, delimiter="`<CUT>`") == ["\nalpha", "\nbeta"]
    assert nlp.naive_merge_with_images(sections, ["img1"], delimiter="`<CUT>`") == (
        ["\nalpha", "\nbeta"],
        ["img1", "img1"],
    )
    assert nlp.naive_merge_docx([("alpha<CUT>beta", "img1")], delimiter="`<CUT>`") == (
        ["\nalpha", "\nbeta"],
        ["img1", "img1"],
    )
