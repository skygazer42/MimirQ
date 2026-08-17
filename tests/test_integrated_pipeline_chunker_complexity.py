from email.message import EmailMessage
from importlib import import_module
from types import SimpleNamespace

import pytest

book_chunker = import_module("app.third_party.integrated_pipeline.chunkers.book")
email_chunker = import_module("app.third_party.integrated_pipeline.chunkers.email")
laws_chunker = import_module("app.third_party.integrated_pipeline.chunkers.laws")


def _callback_recorder():
    calls = []

    def _callback(*args, **kwargs):
        calls.append((args, kwargs))

    return calls, _callback


def _record_sections(recorder, key):
    def _recorder(sections, eng=False):
        recorder.setdefault(key, []).append((list(sections), eng))

    return _recorder


def _patch_tokenizer(monkeypatch, module):
    monkeypatch.setattr(module.rag_tokenizer, "tokenize", lambda text: f"TOK:{text}")
    monkeypatch.setattr(module.rag_tokenizer, "fine_grained_tokenize", lambda text: f"SM:{text}")


def test_book_chunk_pdf_preserves_table_then_chunk_order_and_real_metadata(monkeypatch):
    calls, callback = _callback_recorder()
    recorded = {}
    parser_config = {
        "chunk_token_num": 512,
        "delimiter": "\n!?。；！？",
        "layout_recognize": "Docling",
    }

    _patch_tokenizer(monkeypatch, book_chunker)

    class _PdfParserStub:
        def crop(self, chunk, need_position=True):
            recorded.setdefault("crop_calls", []).append((chunk, need_position))
            positions = {
                "Heading@P1\nParagraph@P1": [(0, 10, 20, 30, 40)],
                "Tail@P2": [(1, 50, 60, 70, 80)],
            }
            return f"image:{chunk}".encode(), positions[chunk]

        def remove_tag(self, chunk):
            recorded.setdefault("remove_tag_calls", []).append(chunk)
            return chunk.replace("@P1", "").replace("@P2", "")

    def _parser(**kwargs):
        recorded["parser_kwargs"] = kwargs
        return (
            [
                ("Chapter 1", "title"),
                ("Body", "text"),
            ],
            [((None, "Table summary"), [(2, 11, 21, 31, 41)])],
            _PdfParserStub(),
        )

    monkeypatch.setattr(book_chunker, "PARSERS", {"docling": _parser})
    monkeypatch.setattr(book_chunker, "random_choices", lambda values, k=0: list(values))
    monkeypatch.setattr(book_chunker, "is_english", lambda values: True)
    monkeypatch.setattr(
        book_chunker,
        "remove_contents_table",
        _record_sections(recorded, "removed"),
    )
    monkeypatch.setattr(book_chunker, "make_colon_as_title", lambda sections: None)
    monkeypatch.setattr(book_chunker, "bullets_category", lambda sections: 1)
    monkeypatch.setattr(
        book_chunker,
        "hierarchical_merge",
        lambda bull, sections, depth: [["Heading@P1", "Paragraph@P1"], ["Tail@P2"]],
    )
    monkeypatch.setattr(
        book_chunker,
        "naive_merge",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("naive_merge should not run")),
    )

    result = book_chunker.chunk(
        "sample.pdf",
        binary=b"%PDF",
        lang="English",
        callback=callback,
        parser_config=parser_config,
    )

    assert result == [
        {
            "docnm_kwd": "sample.pdf",
            "title_tks": "TOK:sample",
            "title_sm_tks": "SM:TOK:sample",
            "content_with_weight": "Table summary",
            "content_ltks": "TOK:Table summary",
            "content_sm_ltks": "SM:TOK:Table summary",
            "doc_type_kwd": "table",
            "page_num_int": [3],
            "position_int": [(3, 11, 21, 31, 41)],
            "top_int": [31],
        },
        {
            "docnm_kwd": "sample.pdf",
            "title_tks": "TOK:sample",
            "title_sm_tks": "SM:TOK:sample",
            "image": b"image:Heading@P1\nParagraph@P1",
            "page_num_int": [1],
            "position_int": [(1, 10, 20, 30, 40)],
            "top_int": [30],
            "content_with_weight": "Heading\nParagraph",
            "content_ltks": "TOK:Heading\nParagraph",
            "content_sm_ltks": "SM:TOK:Heading\nParagraph",
        },
        {
            "docnm_kwd": "sample.pdf",
            "title_tks": "TOK:sample",
            "title_sm_tks": "SM:TOK:sample",
            "image": b"image:Tail@P2",
            "page_num_int": [2],
            "position_int": [(2, 50, 60, 70, 80)],
            "top_int": [70],
            "content_with_weight": "Tail",
            "content_ltks": "TOK:Tail",
            "content_sm_ltks": "SM:TOK:Tail",
        },
    ]
    assert recorded["parser_kwargs"]["filename"] == "sample.pdf"
    assert recorded["parser_kwargs"]["layout_recognizer"] == "Docling"
    assert recorded["removed"] == [([("Chapter 1", "title"), ("Body", "text")], True)]
    assert recorded["crop_calls"] == [
        ("Heading@P1\nParagraph@P1", True),
        ("Tail@P2", True),
    ]
    assert recorded["remove_tag_calls"] == ["Heading@P1\nParagraph@P1", "Tail@P2"]
    assert parser_config["chunk_token_num"] == 0
    assert calls == [((0.1, "Start to parse."), {}), ((0.8, "Finish parsing."), {})]


def test_email_chunk_separates_plain_and_html_sections_and_appends_attachments(monkeypatch):
    calls, callback = _callback_recorder()
    recorded = {}
    message = EmailMessage()
    message["Subject"] = "Quarterly update"
    message["From"] = "alice@example.com"
    message.set_content("Plain body line 1\nPlain body line 2")
    message.add_alternative("<html><body><p>HTML only line</p></body></html>", subtype="html")
    message.add_attachment(
        b"attachment text",
        maintype="text",
        subtype="plain",
        filename="notes.txt",
    )

    _patch_tokenizer(monkeypatch, email_chunker)

    def _txt_parser(text, chunk_token_num=128, delimiter="\n!?;。；！？"):
        recorded["txt_parser_args"] = (text, chunk_token_num, delimiter)
        return [["plain email chunk", ""]]

    def _html_parser(text):
        recorded["html_source"] = text
        return ["html email chunk"]

    def _naive_merge(sections, chunk_token_num, delimiter):
        recorded["merge_call"] = (list(sections), chunk_token_num, delimiter)
        return [section[0] for section in sections]

    def _naive_chunk(filename, payload, callback=None, **kwargs):
        recorded["attachment_call"] = (filename, payload, callback, dict(kwargs))
        return [{"content_with_weight": "attachment chunk", "docnm_kwd": filename}]

    monkeypatch.setattr(email_chunker.TxtParser, "parser_txt", staticmethod(_txt_parser))
    monkeypatch.setattr(email_chunker.HtmlParser, "parser_txt", staticmethod(_html_parser))
    monkeypatch.setattr(email_chunker, "naive_merge", _naive_merge)
    monkeypatch.setattr(email_chunker, "naive_chunk", _naive_chunk)

    result = email_chunker.chunk(
        "mail.eml",
        binary=message.as_bytes(),
        lang="English",
        callback=callback,
    )

    plain_source, chunk_token_num, delimiter = recorded["txt_parser_args"]
    assert "Plain body line 1" in plain_source
    assert "<p>HTML only line</p>" not in plain_source
    assert recorded["html_source"].rstrip() == "<html><body><p>HTML only line</p></body></html>"
    assert chunk_token_num == 128
    assert delimiter == "\n!?;。；！？"
    assert recorded["merge_call"] == (
        [
            ["plain email chunk", ""],
            ("html email chunk", ""),
        ],
        512,
        "\n!?。；！？",
    )
    assert result == [
        {
            "docnm_kwd": "mail.eml",
            "title_tks": "TOK:mail",
            "title_sm_tks": "SM:TOK:mail",
            "page_num_int": [1],
            "position_int": [(1, 0, 0, 0, 0)],
            "top_int": [0],
            "content_with_weight": "plain email chunk",
            "content_ltks": "TOK:plain email chunk",
            "content_sm_ltks": "SM:TOK:plain email chunk",
        },
        {
            "docnm_kwd": "mail.eml",
            "title_tks": "TOK:mail",
            "title_sm_tks": "SM:TOK:mail",
            "page_num_int": [2],
            "position_int": [(2, 1, 1, 1, 1)],
            "top_int": [1],
            "content_with_weight": "html email chunk",
            "content_ltks": "TOK:html email chunk",
            "content_sm_ltks": "SM:TOK:html email chunk",
        },
        {"content_with_weight": "attachment chunk", "docnm_kwd": "notes.txt"},
    ]
    assert recorded["attachment_call"] == ("notes.txt", b"attachment text", callback, {})
    assert calls == []


def test_laws_chunk_pdf_preserves_position_suffix_order_and_real_metadata(monkeypatch):
    calls, callback = _callback_recorder()
    recorded = {}
    parser_config = {
        "chunk_token_num": 512,
        "delimiter": "\n!?。；！？",
        "layout_recognize": "Docling",
    }

    _patch_tokenizer(monkeypatch, laws_chunker)

    class _PdfParserStub:
        def crop(self, chunk, need_position=True):
            recorded.setdefault("crop_calls", []).append((chunk, need_position))
            positions = {
                "MERGED:Section 1@P1": [(0, 1, 2, 3, 4)],
                "MERGED:Body@P2": [(1, 5, 6, 7, 8)],
            }
            return f"image:{chunk}".encode(), positions[chunk]

        def remove_tag(self, chunk):
            recorded.setdefault("remove_tag_calls", []).append(chunk)
            return chunk.replace("@P1", "").replace("@P2", "")

    def _parser(**kwargs):
        recorded["parser_kwargs"] = kwargs
        return [("Section 1", "@P1"), ("Body", "@P2")], [], _PdfParserStub()

    monkeypatch.setattr(laws_chunker, "PARSERS", {"docling": _parser})
    monkeypatch.setattr(
        laws_chunker,
        "remove_contents_table",
        _record_sections(recorded, "removed"),
    )
    monkeypatch.setattr(laws_chunker, "make_colon_as_title", lambda sections: None)
    monkeypatch.setattr(laws_chunker, "bullets_category", lambda sections: 2)
    monkeypatch.setattr(
        laws_chunker,
        "tree_merge",
        lambda bull, sections, depth: [f"MERGED:{item}" for item in sections],
    )

    result = laws_chunker.chunk(
        "rules.pdf",
        binary=b"%PDF",
        lang="English",
        callback=callback,
        parser_config=parser_config,
    )

    assert result == [
        {
            "docnm_kwd": "rules.pdf",
            "title_tks": "TOK:rules",
            "title_sm_tks": "SM:TOK:rules",
            "image": b"image:MERGED:Section 1@P1",
            "page_num_int": [1],
            "position_int": [(1, 1, 2, 3, 4)],
            "top_int": [3],
            "content_with_weight": "MERGED:Section 1",
            "content_ltks": "TOK:MERGED:Section 1",
            "content_sm_ltks": "SM:TOK:MERGED:Section 1",
        },
        {
            "docnm_kwd": "rules.pdf",
            "title_tks": "TOK:rules",
            "title_sm_tks": "SM:TOK:rules",
            "image": b"image:MERGED:Body@P2",
            "page_num_int": [2],
            "position_int": [(2, 5, 6, 7, 8)],
            "top_int": [7],
            "content_with_weight": "MERGED:Body",
            "content_ltks": "TOK:MERGED:Body",
            "content_sm_ltks": "SM:TOK:MERGED:Body",
        },
    ]
    assert recorded["parser_kwargs"]["filename"] == "rules.pdf"
    assert recorded["removed"] == [(["Section 1@P1", "Body@P2"], True)]
    assert recorded["crop_calls"] == [("MERGED:Section 1@P1", True), ("MERGED:Body@P2", True)]
    assert recorded["remove_tag_calls"] == ["MERGED:Section 1@P1", "MERGED:Body@P2"]
    assert parser_config["chunk_token_num"] == 0
    assert calls == [((0.1, "Start to parse."), {}), ((0.8, "Finish parsing."), {})]


def test_laws_chunk_markdown_branch_uses_real_tokenization_and_positions(monkeypatch):
    calls, callback = _callback_recorder()
    recorded = {}

    _patch_tokenizer(monkeypatch, laws_chunker)
    monkeypatch.setattr(laws_chunker, "get_text", lambda filename, binary: "Article 1\nBody line")
    monkeypatch.setattr(
        laws_chunker,
        "remove_contents_table",
        _record_sections(recorded, "removed"),
    )
    monkeypatch.setattr(laws_chunker, "make_colon_as_title", lambda sections: None)
    monkeypatch.setattr(laws_chunker, "bullets_category", lambda sections: 3)
    monkeypatch.setattr(
        laws_chunker,
        "tree_merge",
        lambda bull, sections, depth: [f"{sections[0]}\n{sections[1]}"],
    )

    result = laws_chunker.chunk(
        "rules.md",
        binary=b"# ignored by get_text stub",
        lang="English",
        callback=callback,
    )

    assert result == [
        {
            "docnm_kwd": "rules.md",
            "title_tks": "TOK:rules",
            "title_sm_tks": "SM:TOK:rules",
            "page_num_int": [1],
            "position_int": [(1, 0, 0, 0, 0)],
            "top_int": [0],
            "content_with_weight": "Article 1\nBody line",
            "content_ltks": "TOK:Article 1\nBody line",
            "content_sm_ltks": "SM:TOK:Article 1\nBody line",
        }
    ]
    assert recorded["removed"] == [(["Article 1", "Body line"], True)]
    assert calls == [((0.1, "Start to parse."), {}), ((0.8, "Finish parsing."), {})]


@pytest.mark.parametrize(
    ("module", "filename"),
    [
        (book_chunker, "sample.doc"),
        (laws_chunker, "rules.doc"),
    ],
)
def test_doc_chunk_returns_empty_when_tika_produces_no_content(monkeypatch, module, filename):
    calls, callback = _callback_recorder()

    _patch_tokenizer(monkeypatch, module)
    monkeypatch.setattr(
        module,
        "optional_import",
        lambda *args, **kwargs: SimpleNamespace(from_buffer=lambda buffer: {"content": None}),
    )

    result = module.chunk(
        filename,
        binary=b"legacy-doc-binary",
        lang="English",
        callback=callback,
    )

    assert result == []
    assert calls == [
        ((0.1, "Start to parse."), {}),
        ((0.8, f"tika.parser got empty content from {filename}."), {}),
    ]
