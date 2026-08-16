
from app.rag.retrieval.hybrid.vector_normalizer import normalize_vector_channel_results


def test_vector_normalizer_preserves_order_and_backfills_chunk_ids() -> None:
    results = [
        {
            "content": "existing",
            "chunk_id": 101,
            "metadata": {"document_id": "doc-1", "chunk_index": 0},
        },
        {
            "content": "pipeline lookup",
            "metadata": {
                "document_id": "doc-2",
                "chunk_index": 1,
                "doc_pipeline_key": "doc-2:pipe-a",
            },
        },
        {
            "content": "document lookup",
            "metadata": {"document_id": "doc-3", "chunk_index": 2},
        },
    ]

    normalized = normalize_vector_channel_results(
        results,
        document_ids=None,
        vector_filter=None,
        runtime_shards_present=False,
        chunk_id_lookup={
            "doc-2:pipe-a:1": "chunk-pipe",
            "doc-3:2": "chunk-doc",
        },
        match_metadata_filter=lambda meta, filter_spec: True,  # noqa: ARG005
    )

    assert [item["content"] for item in normalized] == ["existing", "pipeline lookup", "document lookup"]
    assert [item["chunk_id"] for item in normalized] == ["101", "chunk-pipe", "chunk-doc"]
    assert normalized[0]["metadata"]["chunk_id"] == "101"
    assert normalized[1]["metadata"]["chunk_id"] == "chunk-pipe"
    assert normalized[2]["metadata"]["chunk_id"] == "chunk-doc"


def test_vector_normalizer_applies_document_scope_then_client_filter_without_shard_space_hash() -> None:
    seen_filters: list[dict[str, object]] = []

    def _match_metadata_filter(meta: dict[str, object], filter_spec: dict[str, object]) -> bool:
        seen_filters.append(dict(filter_spec))
        return meta.get("dataset_id") == "dataset-1"

    normalized = normalize_vector_channel_results(
        [
            {
                "content": "allowed",
                "metadata": {"document_id": "doc-1", "dataset_id": "dataset-1"},
            },
            {
                "content": "wrong dataset",
                "metadata": {"document_id": "doc-2", "dataset_id": "dataset-2"},
            },
            {
                "content": "missing document",
                "metadata": {"dataset_id": "dataset-1"},
            },
        ],
        document_ids=["doc-1", "doc-2"],
        vector_filter={
            "dataset_id": "dataset-1",
            "embedding_space_hash": {"$in": ["space-a", ""]},
        },
        runtime_shards_present=True,
        chunk_id_lookup=None,
        match_metadata_filter=_match_metadata_filter,
    )

    assert [item["content"] for item in normalized] == ["allowed"]
    assert seen_filters == [{"dataset_id": "dataset-1"}, {"dataset_id": "dataset-1"}]
