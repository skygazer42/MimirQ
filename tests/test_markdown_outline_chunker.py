from langchain_core.documents import Document


def test_markdown_outline_chunker_preserves_offsets_and_header_path():
    from app.rag.chunking.strategies.markdown_outline import MarkdownOutlineChunker

    text = (
        "# Title\n"
        "Intro paragraph.\n\n"
        "## Section One\n"
        "Section one content.\n\n"
        "### Details\n"
        "Detail paragraph A.\n"
        "Detail paragraph B.\n\n"
        "## Section Two\n"
        "Section two content.\n"
    )

    chunker = MarkdownOutlineChunker(chunk_size=140, chunk_overlap=20)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "md"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata or {}
        assert meta.get("chunk_strategy") == "markdown_outline"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    # Ensure nested heading path is preserved.
    nested = [c for c in chunks if (c.metadata or {}).get("outline_path")]
    assert nested
    assert any("Section One" in " / ".join((c.metadata or {}).get("outline_path") or []) for c in nested)
    assert any("Details" in " / ".join((c.metadata or {}).get("outline_path") or []) for c in nested)

