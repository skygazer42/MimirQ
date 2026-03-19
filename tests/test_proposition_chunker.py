from __future__ import annotations

from langchain_core.documents import Document

from app.rag.chunking.strategies.proposition import PropositionChunker


def test_proposition_chunker_emits_atomic_units() -> None:
    text = (
        "Alpha is good. Beta is better!\n\n"
        "```python\nprint('hi')\n```\n\n"
        "- item one\n"
        "- item two\n"
    )
    chunker = PropositionChunker(chunk_size=1000, chunk_overlap=0)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"source": "x"})])

    assert chunks
    kinds = {str(c.metadata.get("proposition_kind") or "") for c in chunks}
    assert "text" in kinds
    assert "code" in kinds
    assert "list" in kinds

    for c in chunks:
        assert c.metadata.get("chunk_strategy") == "proposition"
        assert isinstance(c.metadata.get("start_char"), int)
        assert isinstance(c.metadata.get("end_char"), int)
        assert isinstance(c.metadata.get("chunk_index"), int)

