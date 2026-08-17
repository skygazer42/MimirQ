from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from PIL import Image

from app.deepdoc.parser.mineru_parser import (
    MinerUContentType,
    MinerULanguage,
    MinerUParseMethod,
    MinerUParser,
)
from app.deepdoc.src.model.rag_tokenizer import RagTokenizer
from app.deepdoc.vision.recognizer import Recognizer
from app.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer


def test_table_structure_call_aligns_row_and_column_geometry(monkeypatch) -> None:
    detections = [
        [
            {
                "type": "table row",
                "score": 0.91,
                "bbox": [15, 20, 80, 30],
            },
            {
                "type": "table row",
                "score": 0.89,
                "bbox": [10, 35, 70, 45],
            },
            {
                "type": "table column",
                "score": 0.87,
                "bbox": [5, 12, 25, 60],
            },
            {
                "type": "table column",
                "score": 0.83,
                "bbox": [30, 15, 50, 55],
            },
        ]
    ]
    monkeypatch.setattr(Recognizer, "__call__", lambda self, images, thr: detections)

    recognizer = object.__new__(TableStructureRecognizer)
    result = recognizer(["image"])

    assert result == [
        [
            {
                "label": "table row",
                "score": 0.91,
                "x0": 10,
                "x1": 80,
                "top": 20,
                "bottom": 30,
            },
            {
                "label": "table row",
                "score": 0.89,
                "x0": 10,
                "x1": 80,
                "top": 35,
                "bottom": 45,
            },
            {
                "label": "table column",
                "score": 0.87,
                "x0": 5,
                "x1": 25,
                "top": 12,
                "bottom": 60,
            },
            {
                "label": "table column",
                "score": 0.83,
                "x0": 30,
                "x1": 50,
                "top": 12,
                "bottom": 60,
            },
        ]
    ]


def test_construct_table_preserves_caption_headers_and_body_rendering() -> None:
    boxes = [
        {
            "text": "表 1",
            "layout_type": "caption",
            "x0": 0,
            "x1": 20,
            "top": 0,
            "bottom": 10,
            "page_number": 0,
        },
        {
            "text": "Name",
            "layout_type": "table",
            "x0": 0,
            "x1": 50,
            "top": 20,
            "bottom": 30,
            "page_number": 0,
            "R": "0",
            "C": "0",
            "R_top": 20,
            "R_bott": 30,
            "C_left": 0,
            "C_right": 50,
            "H": 1,
        },
        {
            "text": "Value",
            "layout_type": "table",
            "x0": 60,
            "x1": 110,
            "top": 20,
            "bottom": 30,
            "page_number": 0,
            "R": "0",
            "C": "1",
            "R_top": 20,
            "R_bott": 30,
            "C_left": 60,
            "C_right": 110,
            "H": 1,
        },
        {
            "text": "Foo",
            "layout_type": "table",
            "x0": 0,
            "x1": 50,
            "top": 40,
            "bottom": 50,
            "page_number": 0,
            "R": "1",
            "C": "0",
            "R_top": 40,
            "R_bott": 50,
            "C_left": 0,
            "C_right": 50,
        },
        {
            "text": "42",
            "layout_type": "table",
            "x0": 60,
            "x1": 110,
            "top": 40,
            "bottom": 50,
            "page_number": 0,
            "R": "1",
            "C": "1",
            "R_top": 40,
            "R_bott": 50,
            "C_left": 60,
            "C_right": 110,
        },
    ]

    html = TableStructureRecognizer.construct_table([dict(box) for box in boxes], html=True)
    desc = TableStructureRecognizer.construct_table([dict(box) for box in boxes], html=False)

    assert html == (
        "<table><caption>表 1</caption>\n"
        "<tr><th  >Name</th><th  >Value</th></tr>\n"
        "<tr><td  >Foo</td><td  >42</td></tr>\n"
        "</table>"
    )
    assert desc == ["Name：Foo; Value：42\t—— from 表 1"]


def test_mineru_read_output_uses_sanitized_nested_filename_and_rewrites_assets(tmp_path) -> None:
    parser = object.__new__(MinerUParser)
    parser.logger = logging.getLogger("test.mineru.read_output")

    nested = tmp_path / "report_name"
    nested.mkdir()
    payload = nested / "report_name_content_list.json"
    payload.write_text(
        (
            '[{"type":"text","img_path":"images/page.png","table_img_path":"tables/t.png",'
            '"equation_img_path":"equations/e.png"}]'
        ),
        encoding="utf-8",
    )

    result = parser._read_output(tmp_path, "report name")

    assert result == [
        {
            "type": "text",
            "img_path": str((nested / "images/page.png").resolve()),
            "table_img_path": str((nested / "tables/t.png").resolve()),
            "equation_img_path": str((nested / "equations/e.png").resolve()),
        }
    ]


def test_mineru_transfer_to_sections_preserves_fallbacks_and_tuple_shapes() -> None:
    parser = object.__new__(MinerUParser)
    parser._line_tag = lambda output: f"@@{output['page_idx']}##"
    outputs = [
        {"type": MinerUContentType.TEXT, "text": "Body", "page_idx": 1},
        {
            "type": MinerUContentType.TABLE,
            "table_body": "",
            "table_caption": [],
            "table_footnote": [],
            "page_idx": 2,
        },
        {
            "type": MinerUContentType.IMAGE,
            "image_caption": ["Figure"],
            "image_footnote": [" note"],
            "page_idx": 3,
        },
        {"type": MinerUContentType.DISCARDED, "text": "skip", "page_idx": 4},
    ]

    manual = parser._transfer_to_sections(outputs, parse_method="manual")
    paper = parser._transfer_to_sections(outputs, parse_method="paper")
    raw = parser._transfer_to_sections(outputs, parse_method="raw")

    assert manual == [
        ("Body", MinerUContentType.TEXT, "@@1##"),
        ("FAILED TO PARSE TABLE", MinerUContentType.TABLE, "@@2##"),
        ("Figure\n note", MinerUContentType.IMAGE, "@@3##"),
    ]
    assert paper == [
        ("Body@@1##", MinerUContentType.TEXT),
        ("FAILED TO PARSE TABLE@@2##", MinerUContentType.TABLE),
        ("Figure\n note@@3##", MinerUContentType.IMAGE),
    ]
    assert raw == [
        ("Body", "@@1##"),
        ("FAILED TO PARSE TABLE", "@@2##"),
        ("Figure\n note", "@@3##"),
    ]


def test_mineru_parse_pdf_removes_spaces_and_preserves_option_mapping(tmp_path) -> None:
    parser = MinerUParser(mineru_api="http://mineru.api", mineru_server_url="http://mineru.server")
    input_path = tmp_path / "report name.pdf"
    input_path.write_bytes(b"%PDF-1.4\n")
    captured: dict[str, object] = {}

    parser.__images__ = lambda pdf, zoomin=1: captured.setdefault("images_pdf", Path(pdf).name)

    def _run(
        pdf: str | Path,
        out_dir: str | Path,
        options: object,
        callback: object | None = None,
    ) -> Path:
        captured["pdf_name"] = Path(pdf).name
        captured["out_dir"] = Path(out_dir)
        captured["options"] = options
        return Path(out_dir)

    parser._run_mineru = _run

    def _read_output(
        final_out_dir: object,
        stem: object,
        method: str = "auto",
        backend: str = "pipeline",
    ) -> list[dict[str, object]]:
        del final_out_dir, stem, method, backend
        return [
            {
                "type": MinerUContentType.TEXT,
                "text": "Body",
                "page_idx": 0,
                "bbox": (0, 0, 1, 1),
            }
        ]

    parser._read_output = _read_output
    parser._transfer_to_sections = lambda outputs, parse_method=None: [("section", parse_method, outputs[0]["type"])]
    parser._transfer_to_tables = lambda outputs: [{"count": len(outputs)}]

    sections, tables = parser.parse_pdf(
        filepath=str(input_path),
        binary=b"",
        output_dir=str(tmp_path / "out"),
        parse_method="manual",
        parser_config={
            "mineru_lang": "French",
            "mineru_parse_method": "ocr",
            "mineru_formula_enable": False,
            "mineru_table_enable": False,
        },
    )

    options = captured["options"]
    assert not input_path.exists()
    assert captured["pdf_name"] == "reportname.pdf"
    assert captured["images_pdf"] == "reportname.pdf"
    assert sections == [("section", "manual", MinerUContentType.TEXT)]
    assert tables == [{"count": 1}]
    assert options.backend == "pipeline"
    assert options.lang is MinerULanguage.LATIN
    assert options.method is MinerUParseMethod.OCR
    assert options.server_url is None
    assert options.parse_method == "manual"
    assert options.formula_enable is False
    assert options.table_enable is False


def test_mineru_crop_filters_invalid_pages_and_preserves_page_offsets() -> None:
    parser = object.__new__(MinerUParser)
    parser.logger = logging.getLogger("test.mineru.crop")
    parser.page_images = [
        Image.new("RGB", (20, 50), "white"),
        Image.new("RGB", (20, 50), "white"),
    ]
    parser.page_from = 3

    pic, positions = parser.crop(
        "@@1-2\t1\t10\t5\t20##@@5\t0\t3\t1\t4##",
        need_position=True,
    )

    assert pic is not None
    assert pic.size == (9, 115)
    assert positions == [
        (3, 1, 10, 5, 50),
        (4, 1, 10, 0, 20),
    ]


def test_rag_tokenizer_dfs_groups_repetitive_unknown_characters() -> None:
    class TrieStub(dict):
        def has_keys_with_prefix(self, prefix: str) -> bool:
            return False

    tokenizer = object.__new__(RagTokenizer)
    tokenizer.trie_ = TrieStub()
    tokenizer.key_ = lambda text: text
    tkslist: list[list[tuple[str, tuple[int, str]]]] = []

    result = tokenizer.dfs_(list("aaaaaa"), 0, [], tkslist)

    assert result == 6
    assert tkslist == [[("aaaaaa", (-12, ""))]]


def test_rag_tokenizer_tokenize_preserves_order_across_ambiguous_alignment(monkeypatch) -> None:
    class Stemmer:
        def stem(self, token: str) -> str:
            return token.upper()

    class Lemmatizer:
        def lemmatize(self, token: str) -> str:
            return token

    tokenizer = object.__new__(RagTokenizer)
    tokenizer.DEBUG = False
    tokenizer.stemmer = Stemmer()
    tokenizer.lemmatizer = Lemmatizer()
    tokenizer._str_q2b = lambda text: text
    tokenizer._tradi2simp = lambda text: text
    tokenizer._split_by_lang = lambda line: [
        ("Running tests", False),
        ("甲乙丙丁", True),
        ("42", True),
    ]
    tokenizer.max_forward_ = lambda text: (["甲乙", "丙丁"], 0)
    tokenizer.max_backward_ = lambda text: (["甲", "乙丙丁"], 0)
    tokenizer.merge_ = lambda text: re.sub(r" +", " ", text).strip()

    def _dfs(
        chars: list[str],
        _s: int,
        _pre_tks: list[Any],
        tkslist: list[Any],
        _depth: int = 0,
        _memo: object | None = None,
    ) -> int:
        tkslist.append([("甲乙", (1, "")), ("丙丁", (1, ""))])
        return len(chars)

    tokenizer.dfs_ = _dfs
    tokenizer.sort_tks_ = lambda tkslist: [(["甲乙", "丙丁"], 9)]
    monkeypatch.setattr(
        "app.deepdoc.src.model.rag_tokenizer.word_tokenize",
        lambda text: ["Running", "tests"],
    )

    assert tokenizer.tokenize("ignored") == "RUNNING TESTS 甲乙 丙丁 42"


def test_rag_tokenizer_fine_grained_tokenize_keeps_second_ranked_split_for_chinese_tokens() -> None:
    tokenizer = object.__new__(RagTokenizer)
    tokenizer.english_normalize_ = lambda tokens: tokens

    def _dfs(
        chars: list[str],
        _s: int,
        _pre_tks: list[Any],
        tkslist: list[Any],
        _depth: int = 0,
        _memo: object | None = None,
    ) -> int:
        tkslist.extend(
            [
                [("中文", (1, "")), ("词条", (1, ""))],
                [("中", (1, "")), ("文词条", (1, ""))],
            ]
        )
        return len(chars)

    tokenizer.dfs_ = _dfs
    tokenizer.sort_tks_ = lambda tkslist: [
        (["中文", "词条"], 10),
        (["中", "文词条"], 9),
    ]

    assert tokenizer.fine_grained_tokenize("中文词条 甲乙") == "中 文词条 甲乙"
