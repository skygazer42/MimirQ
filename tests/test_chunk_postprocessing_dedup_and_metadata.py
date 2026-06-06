from uuid import UUID

from langchain_core.documents import Document

from app.parsing.processors.processor import (
    ChunkAssetOptions,
    ChunkAssetStage,
    ChunkDedupStage,
    _should_skip_near_dedup_for_chunk,
)


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


def test_chunk_dedup_stage_preserves_distinct_record_identity_chunks():
    stage = ChunkDedupStage()
    chunks = [
        Document(
            page_content="Requirement: signed request.",
            metadata={"_record_identity": {"key": "record:001"}},
        ),
        Document(
            page_content="Requirement: signed request.",
            metadata={"_record_identity": {"key": "record:002"}},
        ),
        Document(
            page_content="Requirement: signed request.",
            metadata={"_record_identity": {"key": "record:002"}},
        ),
    ]

    out = stage.run(chunks=chunks, enabled=True)

    assert out.duplicates_dropped == 1
    assert [item.metadata["_record_identity"]["key"] for item in out.chunks] == ["record:001", "record:002"]


def test_near_dedup_skips_record_identity_chunks():
    chunk = Document(page_content="Requirement: signed request.", metadata={"_record_identity": {"key": "record:001"}})

    assert _should_skip_near_dedup_for_chunk(chunk) is True


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


def test_chunk_asset_stage_preserves_plugin_metadata_views_and_strategy():
    class _Svc:
        def _extract_and_upload_image_to_minio(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
            return None

        def _extract_img_id_from_content(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
            return None

    stage = ChunkAssetStage(_Svc())
    doc_id = UUID(int=11)
    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    chunk = Document(
        page_content="Record name: account renewal\nRequired material: identity proof.",
        metadata={
            "chunk_strategy": "python_plugin",
            "governance_python_plugin": "plugin:demo-service@1.0.0:governance",
            "chunk_python_plugin": plugin_ref,
            "_retrieval_display_content": "Record name: account renewal",
            "_retrieval_text": "Record: account renewal\nMaterial: identity proof",
            "_indexed_metadata": {"business_type": "demo_service", "record_name": "account renewal"},
            "_display_metadata": {"record_name": "account renewal"},
            "_evaluable_metadata": {"record_name": "account renewal"},
            "_record_identity": {
                "key": "record_name=account renewal",
                "fields": {"record_name": "account renewal"},
            },
        },
    )

    out = stage.run(
        chunks=[chunk],
        tenant_id=UUID(int=12),
        document_id=doc_id,
        options=ChunkAssetOptions(
            dataset_id="ds",
            resolved_backend="basic",
            resolved_chunk_strategy="langchain_recursive",
        ),
    )
    meta = out.chunks[0].metadata

    assert meta["chunk_strategy"] == "python_plugin"
    assert meta["resolved_chunk_strategy"] == "langchain_recursive"
    assert meta["chunk_python_plugin"] == plugin_ref
    assert meta["governance_python_plugin"] == "plugin:demo-service@1.0.0:governance"
    assert meta["_retrieval_text"] == "Record: account renewal\nMaterial: identity proof"
    assert meta["_retrieval_display_content"] == "Record name: account renewal"
    assert meta["_indexed_metadata"] == {
        "business_type": "demo_service",
        "record_name": "account renewal",
    }
    assert meta["_display_metadata"] == {"record_name": "account renewal"}
    assert meta["_evaluable_metadata"] == {"record_name": "account renewal"}
    assert meta["_record_identity"]["key"] == "record_name=account renewal"
    assert meta["chunk_key"] == f"{doc_id}:0"
