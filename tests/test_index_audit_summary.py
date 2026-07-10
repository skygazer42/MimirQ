

def test_compute_index_audit_summary_reports_missing_and_orphan_samples() -> None:
    from uuid import UUID

    from app.services.index_audit_service import compute_index_audit_summary

    tenant_id = UUID("00000000-0000-0000-0000-000000000000")
    dataset_id = UUID("11111111-1111-1111-1111-111111111111")

    out = compute_index_audit_summary(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        active_documents=3,
        active_chunks=10,
        vector_id_missing=2,
        vector_ids_checked=["a", "b", "a"],
        vector_ids_existing={"a"},
        milvus_ids_sample=["a", "x"],
        active_chunk_ids_present={"a"},
        sample_limit=10,
    )

    assert out["active_documents"] == 3
    assert out["active_chunks"] == 10
    assert out["vector_id_missing"] == 2

    assert out["vector_ids_checked"] == 3
    assert out["vector_ids_missing_in_backend"] == 1
    assert out["vector_ids_missing_in_backend_sample"] == ["b"]

    assert out["milvus_ids_sampled"] == 2
    assert out["milvus_orphan_ids_sample"] == ["x"]

