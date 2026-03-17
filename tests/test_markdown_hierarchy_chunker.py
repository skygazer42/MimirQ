from langchain_core.documents import Document

from app.rag.chunking.strategies.markdown_hierarchy import MarkdownHierarchyChunker


def test_markdown_hierarchy_chunker_emits_paragraph_and_sentence_nodes_with_offsets() -> None:
    text = (
        "# Intro\n"
        "\n"
        "Alpha beta. Gamma.\n"
        "\n"
        "## Details\n"
        "\n"
        "Delta. Epsilon.\n"
    )
    chunker = MarkdownHierarchyChunker(chunk_size=200, chunk_overlap=0)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "md"})])

    assert chunks
    assert all((c.metadata or {}).get("chunk_strategy") == "markdown_hierarchy" for c in chunks)

    # Offsets contract: content matches original substring.
    for idx, c in enumerate(chunks):
        meta = c.metadata or {}
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == c.page_content
        assert str(meta.get("hierarchy_node_key") or "").strip()
        assert str(meta.get("hierarchy_level") or "").strip() in {"paragraph", "sentence"}

    paragraphs = [c for c in chunks if (c.metadata or {}).get("hierarchy_level") == "paragraph"]
    sentences = [c for c in chunks if (c.metadata or {}).get("hierarchy_level") == "sentence"]
    assert paragraphs
    assert sentences

    para_keys = {str((c.metadata or {}).get("hierarchy_node_key") or "").strip() for c in paragraphs}
    assert all(str((c.metadata or {}).get("hierarchy_parent_key") or "").strip() in para_keys for c in sentences)

    # Header path should be attached to the non-heading content under each section.
    body_paras = [c for c in paragraphs if not c.page_content.strip().startswith("#")]
    assert any(str((c.metadata or {}).get("header_path") or "").strip() for c in body_paras)
    # And it should propagate to sentence children (at least for the first body paragraph).
    first_body_para_key = str((body_paras[0].metadata or {}).get("hierarchy_node_key") or "").strip()
    child_sents = [c for c in sentences if str((c.metadata or {}).get("hierarchy_parent_key") or "").strip() == first_body_para_key]
    assert child_sents
    assert all(str((c.metadata or {}).get("header_path") or "").strip() for c in child_sents)

