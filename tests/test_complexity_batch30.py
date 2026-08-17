from langchain_core.documents import Document

from app.rag.chunking.strategies.kv_config import KVConfigChunker, _parse_kv_line
from app.rag.chunking.strategies.markdown import MarkdownAwareChunker, MarkdownHeaderChunker
from app.rag.chunking.strategies.markdown_outline import MarkdownOutlineChunker, _iter_headings


def test_kv_line_parser_preserves_export_and_key_validation() -> None:
    lines = [
        "export API_KEY=x",
        "_A.B-C=1",
        "9BAD=x",
        "键=x",
        "exported=x",
        "NO_EQ",
    ]

    assert [_parse_kv_line(line) for line in lines] == [
        "API_KEY",
        "_A.B-C",
        None,
        None,
        "exported",
        None,
    ]


def test_kv_config_chunker_preserves_sections_overlap_keys_and_offsets() -> None:
    text = (
        "preamble note\n"
        "[db]\n"
        "HOST=localhost\n"
        "export PORT=5432\n"
        "USER=admin\n"
        "PASSWORD=secret\n"
        "# tail\n"
        "[api]\n"
        "TOKEN=abc\n"
        "TIMEOUT=30\n"
    )
    chunks = KVConfigChunker(55, 10).split_documents([Document(page_content=text, metadata={"source": "fixture"})])

    assert [
        (
            chunk.page_content,
            chunk.metadata["start_char"],
            chunk.metadata["end_char"],
            chunk.metadata.get("config_section"),
            chunk.metadata.get("kv_count"),
            chunk.metadata.get("kv_keys"),
            chunk.metadata.get("kv_fallback", False),
            chunk.metadata["chunk_index"],
        )
        for chunk in chunks
    ] == [
        ("preamble note", 0, 13, None, None, None, True, 0),
        (
            "[db]\nHOST=localhost\nexport PORT=5432\nUSER=admin\n",
            14,
            62,
            "db",
            3,
            ["HOST", "PORT", "USER"],
            False,
            1,
        ),
        (
            "USER=admin\nPASSWORD=secret\n# tail\n",
            51,
            85,
            "db",
            2,
            ["USER", "PASSWORD"],
            False,
            2,
        ),
        (
            "PASSWORD=secret\n# tail\n",
            62,
            85,
            "db",
            1,
            ["PASSWORD"],
            False,
            3,
        ),
        (
            "[api]\nTOKEN=abc\nTIMEOUT=30\n",
            85,
            112,
            "api",
            2,
            ["TOKEN", "TIMEOUT"],
            False,
            4,
        ),
        ("TIMEOUT=30\n", 101, 112, "api", 1, ["TIMEOUT"], False, 5),
    ]


def test_markdown_outline_ignores_fenced_headings_and_preserves_paths() -> None:
    text = "intro\n# One\nalpha\n~~~\n## hidden\n~~~\n## Two\nbeta\n# Three\ngamma\n"

    assert [(heading.start, heading.end, heading.title, heading.level) for heading in _iter_headings(text)] == [
        (6, 12, "One", 1),
        (36, 43, "Two", 2),
        (48, 56, "Three", 1),
    ]

    chunks = MarkdownOutlineChunker(80, 10).split_documents(
        [Document(page_content=text, metadata={"source": "fixture"})]
    )
    assert [
        (
            chunk.page_content,
            chunk.metadata["start_char"],
            chunk.metadata["end_char"],
            chunk.metadata.get("outline_path_str"),
            chunk.metadata["chunk_index"],
        )
        for chunk in chunks
    ] == [
        ("intro", 0, 5, None, 0),
        ("# One\nalpha\n~~~\n## hidden\n~~~", 6, 35, "One", 1),
        ("## Two\nbeta", 36, 47, "One / Two", 2),
        ("# Three\ngamma", 48, 61, "Three", 3),
    ]


def test_markdown_header_chunker_preserves_subchunk_positions_and_paths() -> None:
    text = "# Alpha\n" + ("sentence words " * 20) + "\n## Beta\nshort\n"
    chunks = MarkdownHeaderChunker(80, 10).split_documents(
        [Document(page_content=text, metadata={"source": "fixture"})]
    )

    assert [
        (
            chunk.metadata["start_char"],
            chunk.metadata["end_char"],
            chunk.metadata["header_path"],
            chunk.metadata.get("sub_chunk_index"),
        )
        for chunk in chunks
    ] == [
        (0, 7, "Alpha", 0),
        (8, 82, "Alpha", 1),
        (77, 151, "Alpha", 2),
        (143, 217, "Alpha", 3),
        (212, 286, "Alpha", 4),
        (278, 307, "Alpha", 5),
        (309, 322, "Alpha > Beta", None),
    ]


def test_markdown_aware_chunker_preserves_list_items_and_header_context() -> None:
    body = "- first\n  continuation\n\n  more\n- second\nend\n"
    chunker = MarkdownAwareChunker(80, 10)

    assert chunker._protect_list_items(body) == (
        "__LIST_ITEM_0____LIST_ITEM_1__end\n",
        {
            "__LIST_ITEM_0__": "- first\n  continuation\n\n  more\n",
            "__LIST_ITEM_1__": "- second\n",
        },
    )

    text = "# Tasks\n" + body
    chunks = chunker.split_documents([Document(page_content=text, metadata={"source": "fixture"})])
    assert [(chunk.page_content, chunk.metadata) for chunk in chunks] == [
        (
            text.rstrip(),
            {
                "source": "fixture",
                "chunk_strategy": "markdown_aware",
                "chunk_index": 0,
                "start_char": 0,
                "end_char": 51,
                "header_context": "# Tasks",
                "header_path": "# Tasks",
            },
        )
    ]
