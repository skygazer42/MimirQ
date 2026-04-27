from __future__ import annotations

from langchain_core.documents import Document


def test_raptor_chunker_emits_leaf_and_summary_layers() -> None:
    from app.rag.chunking.strategies.raptor import RaptorChunker

    chunker = RaptorChunker(chunk_size=80, chunk_overlap=0, summary_cluster_size=2)
    docs = [
        Document(
            page_content=(
                "Alpha service provisions accounts. "
                "Beta worker syncs ledgers. "
                "Gamma notifier sends callbacks. "
                "Delta auditor validates policy exceptions."
            ),
            metadata={"source": "ops.md"},
        )
    ]

    out = chunker.split_documents(docs)

    leafs = [doc for doc in out if (doc.metadata or {}).get("raptor_layer") == 0]
    summaries = [doc for doc in out if (doc.metadata or {}).get("raptor_layer") == 1]

    assert leafs, "expected base leaf chunks"
    assert summaries, "expected summary parent chunks"
    assert all((doc.metadata or {}).get("chunk_strategy") == "raptor" for doc in out)
    assert all((doc.metadata or {}).get("hierarchy_basis") == "raptor" for doc in out)
    assert all((doc.metadata or {}).get("chunk_role") == "leaf" for doc in leafs)
    assert all((doc.metadata or {}).get("chunk_role") == "summary" for doc in summaries)
    assert all((doc.metadata or {}).get("raptor_tree_mode") == "collapsed" for doc in out)
    assert any((doc.metadata or {}).get("raptor_parent_id") for doc in leafs)


def test_chunker_factory_supports_raptor_strategy() -> None:
    from app.rag.chunking.factory import chunker_factory
    from app.rag.chunking.strategies.raptor import RaptorChunker

    chunker = chunker_factory.get_chunker("raptor", chunk_size=120, chunk_overlap=20)
    assert isinstance(chunker, RaptorChunker)
