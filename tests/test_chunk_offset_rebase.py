from langchain_core.documents import Document

from app.parsing.processors.support.chunk_postprocess import (
    _build_page_start_offsets,
    _rebase_chunk_offsets_by_page_index,
)


def test_duplicate_page_index_keeps_first_document_offset() -> None:
    documents = [
        Document(page_content="alpha", metadata={"page_index": 1}),
        Document(page_content="beta", metadata={"page_index": 1}),
    ]
    chunk = Document(
        page_content="lph",
        metadata={"page_index": 1, "start_char": 1, "end_char": 4},
    )

    assert _build_page_start_offsets(documents, join_separator="\n\n") == {1: 0}

    [rebased] = _rebase_chunk_offsets_by_page_index(
        documents=documents,
        chunks=[chunk],
        join_separator="\n\n",
    )

    assert rebased.metadata["start_char"] == 1
    assert rebased.metadata["end_char"] == 4
    assert rebased.metadata["start_char_local"] == 1
    assert rebased.metadata["end_char_local"] == 4
    assert rebased.metadata["start_char_base"] == 0
