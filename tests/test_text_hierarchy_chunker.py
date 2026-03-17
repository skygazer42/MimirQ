from langchain_core.documents import Document

from app.rag.chunking.strategies.text_hierarchy import TextHierarchyChunker


def test_text_hierarchy_chunker_emits_paragraph_and_sentence_nodes_with_offsets() -> None:
    text = (
        "Para one. Sentence two.\n"
        "\n"
        "Para two line one.\n"
        "Para two line two.\n"
    )
    chunker = TextHierarchyChunker(chunk_size=200, chunk_overlap=0)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    assert all((c.metadata or {}).get("chunk_strategy") == "text_hierarchy" for c in chunks)

    for idx, c in enumerate(chunks):
        meta = c.metadata or {}
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == c.page_content
        assert str(meta.get("hierarchy_node_key") or "").strip()
        assert str(meta.get("hierarchy_level") or "").strip() in {"paragraph", "sentence"}
        assert str(meta.get("hierarchy_basis") or "").strip() == "text_hierarchy"
        assert str(meta.get("chunk_role") or "").strip() in {"paragraph", "sentence"}

    paragraphs = [c for c in chunks if (c.metadata or {}).get("chunk_role") == "paragraph"]
    sentences = [c for c in chunks if (c.metadata or {}).get("chunk_role") == "sentence"]
    assert paragraphs
    assert sentences

    para_keys = {str((c.metadata or {}).get("hierarchy_node_key") or "").strip() for c in paragraphs}
    assert all(str((c.metadata or {}).get("hierarchy_parent_key") or "").strip() in para_keys for c in sentences)

