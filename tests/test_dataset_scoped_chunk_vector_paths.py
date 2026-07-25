from pathlib import Path


def _function_source(path: str, function_name: str, next_marker: str) -> str:
    source = Path(path).read_text(encoding="utf-8")
    try:
        start = source.index(f"def {function_name}(")
    except ValueError:
        start = source.index(f"async def {function_name}(")
    end = source.index(next_marker, start)
    return source[start:end]


def test_manual_chunk_mutations_route_vector_ops_through_indexer_helpers() -> None:
    source_path = "app/api/v1/document_chunks_write.py"

    create_source = _function_source(source_path, "create_document_chunk", "@router.patch(")
    assert "upsert_document_chunk_vector" in create_source
    assert "get_vector_store().add_documents" not in create_source

    patch_source = _function_source(source_path, "patch_document_chunk", "@router.delete(")
    assert "delete_document_chunk_vectors" in patch_source
    assert "upsert_document_chunk_vector" in patch_source
    assert "vector_store.add_documents" not in patch_source
    assert "vector_store.delete_by_document_id_and_filter" not in patch_source

    delete_source = _function_source(source_path, "delete_document_chunk", "@router.post(")
    assert "delete_document_chunk_vectors" in delete_source
    assert "get_vector_store().delete_by_document_id_and_filter" not in delete_source

    disable_source = _function_source(source_path, "disable_document_chunk", "@router.post(")
    assert "delete_document_chunk_vectors" in disable_source
    assert "get_vector_store().delete_by_document_id_and_filter" not in disable_source

    reembed_source = _function_source(source_path, "reembed_document_chunks", "    return {")
    assert "delete_document_chunk_vectors" in reembed_source
    assert "upsert_document_chunk_vector" in reembed_source
    assert "vector_store.add_documents" not in reembed_source
    assert "vector_store.delete_by_document_id_and_filter" not in reembed_source


def test_version_cleanup_routes_vector_ops_through_indexer_helpers() -> None:
    version_source = _function_source(
        "app/api/v1/document_versions.py",
        "delete_document_version",
        "    return Response(status_code=204)",
    )
    assert "Indexer(db).delete_document_chunk_vectors" in version_source
    assert "get_vector_store().delete_by_document_id_and_filter" not in version_source

    retention_source = _function_source(
        "app/services/retention_policy.py",
        "delete_document_version_best_effort",
        "async def run_dataset_retention_sweep(",
    )
    assert "Indexer(db).delete_document_chunk_vectors" in retention_source
    assert "get_vector_store().delete_by_document_id_and_filter" not in retention_source
