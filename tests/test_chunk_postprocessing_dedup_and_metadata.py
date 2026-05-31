from uuid import UUID

from langchain_core.documents import Document

from app.parsing.processors.processor import ChunkAssetOptions, ChunkAssetStage, ChunkDedupStage


def test_chunk_dedup_stage_drops_exact_duplicates_but_keeps_assets():
    stage = ChunkDedupStage()
    chunks = [
        Document(page_content="hello", metadata={}),
        Document(page_content="hello", metadata={}),  # duplicate text
        Document(page_content="hello", metadata={"doc_type_kwd": "image"}),  # keep (asset)
        Document(page_content="world", metadata={}),
    ]

    out = stage.run(chunks=chunks, enabled=True)
    assert out.duplicates_dropped == 1
    assert len(out.chunks) == 3

    # Hash metadata is injected for downstream use.
    assert isinstance(out.chunks[0].metadata.get("content_hash"), str)
    assert out.chunks[0].metadata.get("content_hash_algo") == "sha256"


def test_chunk_asset_stage_sets_chunk_key_and_content_hash():
    class _Svc:
        def _extract_and_upload_image_to_minio(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
            return None

        def _extract_img_id_from_content(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
            return None

    stage = ChunkAssetStage(_Svc())
    doc_id = UUID(int=1)
    chunks = [Document(page_content="hello", metadata={}), Document(page_content="world", metadata={})]

    out = stage.run(
        chunks=chunks,
        tenant_id=UUID(int=2),
        document_id=doc_id,
        options=ChunkAssetOptions(
            dataset_id="ds",
            resolved_backend="basic",
            resolved_chunk_strategy="langchain_recursive",
        ),
    )

    assert out.chunks[0].metadata["chunk_index"] == 0
    assert out.chunks[0].metadata["chunk_key"] == f"{doc_id}:0"
    assert out.chunks[0].metadata["hierarchy_node_key"] == f"{doc_id}:0"
    assert out.chunks[0].metadata["hierarchy_family_key"] == f"{doc_id}:0"
    assert out.chunks[0].metadata["hierarchy_sibling_index"] == 0
    assert isinstance(out.chunks[0].metadata.get("content_hash"), str)
    assert out.chunks[0].metadata.get("content_hash_algo") == "sha256"
    assert out.chunks[0].metadata.get("content_len") == 5
