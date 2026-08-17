from langchain_core.documents import Document

from app.rag.chunking.strategies.maven_pom import MavenPOMChunker, _iter_records
from app.rag.chunking.strategies.toml_config import TOMLConfigChunker, _parse_toml_key_line


def test_maven_pom_chunker_preserves_preamble_records_and_artifacts() -> None:
    text = (
        "<project>\n"
        "<modelVersion>4.0.0</modelVersion>\n"
        "<dependencies>\n"
        "<dependency><groupId>a</groupId><artifactId>one</artifactId></dependency>\n"
        "<dependency><groupId>b</groupId><artifactId>two</artifactId></dependency>\n"
        "</dependencies>\n"
        "<build><plugins>\n"
        "<plugin><groupId>c</groupId><artifactId>three</artifactId></plugin>\n"
        "</plugins></build>\n"
        "</project>\n"
    )
    assert [(record.start, record.end, record.index, record.kind, record.ga) for record in _iter_records(text)] == [
        (60, 134, 0, "dependency", "a:one"),
        (134, 208, 1, "dependency", "b:two"),
        (241, 309, 2, "plugin", "c:three"),
    ]

    chunks = MavenPOMChunker(135, 25).split_documents([Document(page_content=text, metadata={"source": "fixture"})])
    assert [
        (
            chunk.metadata["start_char"],
            chunk.metadata["end_char"],
            chunk.metadata.get("maven_pom_preamble", False),
            chunk.metadata.get("maven_record_count"),
            chunk.metadata.get("maven_kinds"),
            chunk.metadata.get("maven_artifacts"),
            chunk.metadata["chunk_index"],
        )
        for chunk in chunks
    ] == [
        (0, 59, True, None, None, None, 0),
        (60, 134, False, 1, ["dependency"], ["a:one"], 1),
        (134, 208, False, 1, ["dependency"], ["b:two"], 2),
        (241, 309, False, 1, ["plugin"], ["c:three"], 3),
    ]


def test_toml_chunker_preserves_tables_entry_overlap_and_offsets() -> None:
    lines = [
        "a = 1",
        "bad = # comment",
        'x-y = "v"',
        "键 = 1",
        "arr = [1, 2] # ok",
    ]
    assert [_parse_toml_key_line(line) for line in lines] == [
        "a",
        None,
        "x-y",
        None,
        "arr",
    ]

    text = 'title = "demo"\n[tool.one]\na = 1\nb = 2\nc = 3\n[tool.two]\nx = "yes"\ny = "no"\n'
    chunks = TOMLConfigChunker(35, 8).split_documents([Document(page_content=text, metadata={"source": "fixture"})])
    assert [
        (
            chunk.page_content,
            chunk.metadata["start_char"],
            chunk.metadata["end_char"],
            chunk.metadata.get("toml_table"),
            chunk.metadata["toml_entry_count"],
            chunk.metadata["toml_keys"],
            chunk.metadata["chunk_index"],
        )
        for chunk in chunks
    ] == [
        ('title = "demo"\n', 0, 15, None, 1, ["title"], 0),
        ("a = 1\nb = 2\nc = 3\n", 26, 44, "table:tool.one", 3, ["a", "b", "c"], 1),
        ("c = 3\n", 38, 44, "table:tool.one", 1, ["c"], 2),
        ('x = "yes"\ny = "no"\n', 55, 74, "table:tool.two", 2, ["x", "y"], 3),
        ('y = "no"\n', 65, 74, "table:tool.two", 1, ["y"], 4),
    ]
