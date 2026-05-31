from __future__ import annotations

import uuid

from langchain_core.documents import Document

from app.parsing.processors.processor import ChunkAssetOptions, ChunkAssetStage
from app.rag.retriever import HybridRetriever


class _FakeProcessorSvc:
    """
    Minimal stub for ChunkAssetStage unit tests.

    These tests focus on adjacency metadata and retrieval stitching logic;
    avoid MinIO and image decoding.
    """

    def _extract_and_upload_image_to_minio(  # noqa: ANN001
        self,
        metadata,
        tenant_id,
        dataset_id,
        document_id,
        chunk_index,
        **_kwargs,
    ):
        metadata.pop("image", None)
        return None

    def _extract_img_id_from_content(self, _content):  # noqa: ANN001
        return None


def test_chunk_asset_stage_sets_prev_next_adjacency_metadata():  # noqa: ANN001
    stage = ChunkAssetStage(_FakeProcessorSvc())

    tenant_id = uuid.uuid4()
    dataset_id = str(uuid.uuid4())
    document_id = uuid.uuid4()

    chunks = [
        Document(page_content="A", metadata={"doc_type_kwd": "text", "page": 1, "source": "demo.txt"}),
        Document(page_content="B", metadata={"doc_type_kwd": "text", "page": 1, "source": "demo.txt"}),
        Document(page_content="C", metadata={"doc_type_kwd": "text", "page": 2, "source": "demo.txt"}),
    ]

    res = stage.run(
        chunks=chunks,
        tenant_id=tenant_id,
        document_id=document_id,
        options=ChunkAssetOptions(
            dataset_id=dataset_id,
            resolved_backend="docling",
            resolved_chunk_strategy="auto",
            image_caption_enabled=False,
            image_ocr_enabled=False,
        ),
    )

    out = res.chunks
    assert [int((c.metadata or {}).get("chunk_index")) for c in out] == [0, 1, 2]

    for i, c in enumerate(out):
        meta = c.metadata or {}
        assert meta.get("prev_chunk_index") == (i - 1 if i > 0 else None)
        assert meta.get("next_chunk_index") == (i + 1 if i < (len(out) - 1) else None)

        expected_prev_key = f"{document_id}:{i - 1}" if i > 0 else None
        expected_next_key = f"{document_id}:{i + 1}" if i < (len(out) - 1) else None
        assert meta.get("prev_chunk_key") == expected_prev_key
        assert meta.get("next_chunk_key") == expected_next_key
        assert meta.get("hierarchy_sibling_index") == i
        assert meta.get("hierarchy_prev_sibling_key") == expected_prev_key
        assert meta.get("hierarchy_next_sibling_key") == expected_next_key
        assert meta.get("hierarchy_basis") == "chunk_sequence"
        assert meta.get("hierarchy_level") == "chunk"
        assert meta.get("hierarchy_node_key") == f"{document_id}:{i}"
        assert meta.get("hierarchy_family_key") == f"{document_id}:{i}"
        assert meta.get("hierarchy_prev_sibling_key") == expected_prev_key
        assert meta.get("hierarchy_next_sibling_key") == expected_next_key


def test_retrieval_stitching_orders_contiguous_chunks(monkeypatch):  # noqa: ANN001
    # Enable stitching for this unit test; default config keeps it off.
    from app.core.config import settings

    monkeypatch.setattr(settings, "RAG_CONTEXT_STITCHING_ENABLED", True, raising=False)

    retriever = HybridRetriever()

    doc_a = str(uuid.uuid4())
    doc_b = str(uuid.uuid4())

    # Intentionally scrambled order: stitching should group by (document_id, contiguous chunk_index),
    # then sort within each group by chunk_index.
    results = [
        {"chunk_id": "a3", "content": "A3", "metadata": {"document_id": doc_a, "chunk_index": 3}, "score": 0.90},
        {"chunk_id": "b5", "content": "B5", "metadata": {"document_id": doc_b, "chunk_index": 5}, "score": 0.85},
        {"chunk_id": "a2", "content": "A2", "metadata": {"document_id": doc_a, "chunk_index": 2}, "score": 0.80},
        {"chunk_id": "a1", "content": "A1", "metadata": {"document_id": doc_a, "chunk_index": 1}, "score": 0.70},
        {"chunk_id": "b6", "content": "B6", "metadata": {"document_id": doc_b, "chunk_index": 6}, "score": 0.60},
    ]

    stitched = retriever._stitch_results_for_continuity(results)
    stitched_ids = [r.get("chunk_id") for r in stitched]
    assert stitched_ids == ["a1", "a2", "a3", "b5", "b6"]
