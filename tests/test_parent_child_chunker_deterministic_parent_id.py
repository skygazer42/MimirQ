from __future__ import annotations

from langchain_core.documents import Document

from app.rag.chunking.strategies.parent_child import ParentChildChunker


def test_parent_child_chunker_parent_ids_are_deterministic() -> None:
    chunker = ParentChildChunker(chunk_size=120, chunk_overlap=20, child_ratio=0.5, min_child_size=60)

    # Ensure we produce multiple parent chunks.
    content = "\n\n".join(
        [
            "Section 1: " + ("A" * 140),
            "Section 2: " + ("B" * 140),
            "Section 3: " + ("C" * 140),
        ]
    )

    out1 = chunker.split_documents([Document(page_content=content, metadata={"source": "t"})])
    out2 = chunker.split_documents([Document(page_content=content, metadata={"source": "t"})])

    parents1 = [d for d in out1 if (d.metadata or {}).get("chunk_role") == "parent"]
    parents2 = [d for d in out2 if (d.metadata or {}).get("chunk_role") == "parent"]
    assert len(parents1) >= 2
    assert len(parents2) == len(parents1)

    parent_ids1 = [str((d.metadata or {}).get("parent_id") or "") for d in parents1]
    parent_ids2 = [str((d.metadata or {}).get("parent_id") or "") for d in parents2]

    assert all(pid for pid in parent_ids1)
    assert parent_ids1 == parent_ids2

