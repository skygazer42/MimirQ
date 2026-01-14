from langchain_core.documents import Document

from app.rag.chunking.strategies.outline import OutlineChunker


def test_outline_chunker_preserves_offsets_and_heading_path():
    text = (
        "1. Chapter One\n"
        "This is the first chapter.\n\n"
        "1.1 Section One\n"
        "Details in section one.\n\n"
        "2. Chapter Two\n"
        "Second chapter content.\n"
    )
    chunker = OutlineChunker(chunk_size=120, chunk_overlap=20)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "outline"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    # Ensure at least one chunk is tagged with the nested heading.
    nested = [c for c in chunks if (c.metadata or {}).get("outline_level") == 2]
    assert nested
    assert any("1.1" in str(c.metadata.get("outline_heading", "")) for c in nested)
    assert any("outline_path" in (c.metadata or {}) for c in nested)

