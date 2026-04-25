from __future__ import annotations


def test_build_semantic_leiden_proxy_clusters_groups_related_leaf_chunks() -> None:
    from app.rag.chunking.strategies.raptor import build_semantic_leiden_proxy_clusters

    clusters = build_semantic_leiden_proxy_clusters(
        [
            "billing invoice tax reconciliation",
            "invoice tax export mismatch",
            "warehouse shipment pallet tracking",
            "shipment pallet manifest",
        ],
        similarity_threshold=0.2,
    )

    assert clusters == [[0, 1], [2, 3]]


def test_raptor_chunker_uses_leiden_proxy_metadata_when_enabled() -> None:
    from langchain_core.documents import Document

    from app.rag.chunking.strategies.raptor import RaptorChunker

    chunker = RaptorChunker(
        chunk_size=80,
        chunk_overlap=0,
        summary_cluster_size=2,
        cluster_strategy="leiden_proxy",
        similarity_threshold=0.2,
    )
    out = chunker.split_documents(
        [
            Document(
                page_content=(
                    "Billing invoice tax reconciliation is pending. "
                    "Invoice export mismatch affects the tax line. "
                    "Warehouse shipment pallet tracking is delayed. "
                    "Shipment pallet manifest needs review."
                ),
                metadata={},
            )
        ]
    )

    summaries = [doc for doc in out if (doc.metadata or {}).get("raptor_layer") == 1]
    assert summaries
    assert all((doc.metadata or {}).get("raptor_cluster_strategy") == "leiden_proxy" for doc in summaries)
