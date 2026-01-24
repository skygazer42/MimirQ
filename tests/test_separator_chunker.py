from langchain_core.documents import Document

from app.rag.chunking.strategies.separator import SeparatorChunker


def test_separator_chunker_preserves_offsets_keep_separator_true():
    text = "A\n\nB\n\nC"
    chunker = SeparatorChunker(
        chunk_size=1000,
        chunk_overlap=0,
        separator="\n\n",
        keep_separator=True,
        max_chunk_size=1000,
    )
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "md"})])

    assert [c.page_content for c in chunks] == ["A\n\n", "B\n\n", "C"]
    for c in chunks:
        meta = c.metadata or {}
        assert meta.get("chunk_strategy") == "separator"
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == c.page_content


def test_separator_chunker_preserves_offsets_keep_separator_false_trims():
    text = "  A  \n\n  B  \n\nC   "
    chunker = SeparatorChunker(
        chunk_size=1000,
        chunk_overlap=0,
        separator="\n\n",
        keep_separator=False,
        max_chunk_size=1000,
    )
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "md"})])

    assert [c.page_content for c in chunks] == ["A", "B", "C"]
    for c in chunks:
        meta = c.metadata or {}
        assert meta.get("chunk_strategy") == "separator"
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == c.page_content


def test_separator_chunker_splits_large_chunk_and_preserves_offsets():
    text = "Sentence 1. Sentence 2. Sentence 3. Sentence 4. Sentence 5."
    chunker = SeparatorChunker(
        chunk_size=1000,
        chunk_overlap=0,
        separator="|||",  # does not appear in text -> single large part
        keep_separator=False,
        max_chunk_size=20,
    )
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert len(chunks) > 1
    for c in chunks:
        meta = c.metadata or {}
        assert meta.get("chunk_strategy") == "separator"
        assert meta.get("is_sub_chunk") is True
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == c.page_content

