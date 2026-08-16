
import uuid

from app.rag.retrieval.hybrid.cache_scope import prepare_hybrid_cache_scope


def test_prepare_hybrid_cache_scope_fail_closed_for_missing_document_runtime() -> None:
    decision = prepare_hybrid_cache_scope(
        cache_enabled=True,
        distributed_singleflight_enabled=True,
        semantic_cache_enabled=True,
        semantic_cache_dataset_scoped=False,
        tenant_id=uuid.uuid4(),
        account_id=" member-1 ",
        dataset_scope_ids=(),
        document_ids=[uuid.uuid4()],
        metadata_filter_dataset_scoped=False,
        document_scope_resolution_failed=True,
        runtime_scope_ids=(),
        runtime_shard_count=0,
        runtime_scope_missing_dataset_ids=(),
        runtime_pipeline_values=[],
        embedding_space="space-a",
        cache_ttl=60,
        semantic_cache_ttl=60,
    )

    assert decision.account_id == "member-1"
    assert decision.document_ids and len(decision.document_ids) == 1
    assert decision.scope_failure_reason == "missing_document_runtime"
    assert decision.cache_eligible is False
    assert decision.distributed_singleflight_eligible is False
    assert decision.semantic_cache_eligible is False
    assert decision.cache_meta["skip_reason"] == "missing_document_runtime"
    assert decision.cache_meta["semantic"]["skip_reason"] == "missing_document_runtime"


def test_prepare_hybrid_cache_scope_preserves_signature_inputs_and_multi_runtime_semantic_gate() -> None:
    first_document_id = uuid.uuid4()
    second_document_id = uuid.uuid4()

    decision = prepare_hybrid_cache_scope(
        cache_enabled=True,
        distributed_singleflight_enabled=True,
        semantic_cache_enabled=True,
        semantic_cache_dataset_scoped=False,
        tenant_id=uuid.uuid4(),
        account_id="member-1",
        dataset_scope_ids=(uuid.uuid4(), uuid.uuid4()),
        document_ids=[second_document_id, first_document_id],
        metadata_filter_dataset_scoped=False,
        document_scope_resolution_failed=False,
        runtime_scope_ids=(uuid.uuid4(), uuid.uuid4()),
        runtime_shard_count=2,
        runtime_scope_missing_dataset_ids=(),
        runtime_pipeline_values=["space-b", "", "space-a", "space-b"],
        embedding_space="fallback-space",
        cache_ttl=60,
        semantic_cache_ttl=60,
    )

    assert decision.dataset_id is None
    assert decision.pipeline_key == "space-a,space-b"
    assert decision.document_ids == [str(second_document_id), str(first_document_id)]
    assert decision.scope_failure_reason is None
    assert decision.cache_eligible is True
    assert decision.distributed_singleflight_eligible is True
    assert decision.semantic_cache_eligible is False
    assert decision.cache_meta["enabled"] is True
    assert decision.cache_meta["singleflight_enabled"] is True
    assert decision.cache_meta["semantic"]["enabled"] is False
    assert decision.cache_meta["semantic"]["skip_reason"] == "multi_runtime_scope"


def test_prepare_hybrid_cache_scope_missing_scope_and_ttl_rules_match_existing_semantics() -> None:
    missing_scope = prepare_hybrid_cache_scope(
        cache_enabled=True,
        distributed_singleflight_enabled=True,
        semantic_cache_enabled=True,
        semantic_cache_dataset_scoped=False,
        tenant_id=uuid.uuid4(),
        account_id="member-1",
        dataset_scope_ids=(),
        document_ids=None,
        metadata_filter_dataset_scoped=False,
        document_scope_resolution_failed=False,
        runtime_scope_ids=(),
        runtime_shard_count=0,
        runtime_scope_missing_dataset_ids=(),
        runtime_pipeline_values=[],
        embedding_space="space-a",
        cache_ttl=60,
        semantic_cache_ttl=60,
    )
    ttl_zero = prepare_hybrid_cache_scope(
        cache_enabled=True,
        distributed_singleflight_enabled=True,
        semantic_cache_enabled=True,
        semantic_cache_dataset_scoped=False,
        tenant_id=uuid.uuid4(),
        account_id="member-1",
        dataset_scope_ids=(uuid.uuid4(),),
        document_ids=None,
        metadata_filter_dataset_scoped=False,
        document_scope_resolution_failed=False,
        runtime_scope_ids=(uuid.uuid4(),),
        runtime_shard_count=1,
        runtime_scope_missing_dataset_ids=(),
        runtime_pipeline_values=["space-a"],
        embedding_space="space-a",
        cache_ttl=0,
        semantic_cache_ttl=60,
    )

    assert missing_scope.cache_eligible is False
    assert missing_scope.distributed_singleflight_eligible is False
    assert missing_scope.semantic_cache_eligible is False
    assert missing_scope.cache_meta["skip_reason"] == "missing_scope"
    assert missing_scope.cache_meta["semantic"]["skip_reason"] == "missing_scope"

    assert ttl_zero.scope_failure_reason is None
    assert ttl_zero.cache_eligible is False
    assert ttl_zero.distributed_singleflight_eligible is True
    assert ttl_zero.semantic_cache_eligible is True
    assert ttl_zero.cache_meta["skip_reason"] == "ttl_zero"
    assert ttl_zero.cache_meta["singleflight_enabled"] is True
    assert ttl_zero.cache_meta["semantic"]["enabled"] is True
