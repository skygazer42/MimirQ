from __future__ import annotations

from langchain_core.documents import Document

from app.rag.chunking.strategies.auto import AutoChunker


def test_auto_chunker_adapts_chunk_size_by_density() -> None:
    """
    Regression/feature: auto chunker should adapt chunk_size based on simple density metrics.

    We validate via the per-chunk metadata the auto chunker emits for debug/traceability.
    """
    base_size = 1000
    base_overlap = 200
    chunker = AutoChunker(chunk_size=base_size, chunk_overlap=base_overlap)

    dense = Document(page_content="a" * 3200, metadata={"file_type": "txt", "source": "dense.txt"})
    # Many short lines => low avg_line_len => sparse layout.
    sparse = Document(page_content=("a\n" * 2000), metadata={"file_type": "txt", "source": "sparse.txt"})

    dense_chunks = chunker.split_documents([dense])
    sparse_chunks = chunker.split_documents([sparse])

    assert dense_chunks and sparse_chunks

    dense_sizes = {int(c.metadata.get("chunk_size_effective") or 0) for c in dense_chunks}
    sparse_sizes = {int(c.metadata.get("chunk_size_effective") or 0) for c in sparse_chunks}

    assert len(dense_sizes) == 1
    assert len(sparse_sizes) == 1

    dense_size = next(iter(dense_sizes))
    sparse_size = next(iter(sparse_sizes))

    assert dense_size < base_size
    assert sparse_size > base_size

