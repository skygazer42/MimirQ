
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HybridCacheScopeDecision:
    account_id: str
    dataset_id: str | None
    pipeline_key: str | None
    document_ids: list[str]
    cache_eligible: bool
    distributed_singleflight_eligible: bool
    semantic_cache_eligible: bool
    cache_meta: dict[str, Any]
    scope_failure_reason: str | None


def prepare_hybrid_cache_scope(
    *,
    cache_enabled: bool,
    distributed_singleflight_enabled: bool,
    semantic_cache_enabled: bool,
    semantic_cache_dataset_scoped: bool,
    tenant_id: Any,
    account_id: str | None,
    dataset_scope_ids: tuple[Any, ...],
    document_ids: list[Any] | None,
    metadata_filter_dataset_scoped: bool,
    document_scope_resolution_failed: bool,
    runtime_scope_ids: tuple[Any, ...],
    runtime_shard_count: int,
    runtime_scope_missing_dataset_ids: tuple[Any, ...],
    runtime_pipeline_values: list[str],
    embedding_space: str | None,
    cache_ttl: int,
    semantic_cache_ttl: int,
) -> HybridCacheScopeDecision:
    account_id0 = (account_id or "").strip()
    dataset_id0 = str(dataset_scope_ids[0]) if len(dataset_scope_ids) == 1 else None
    pipeline_parts = sorted({str(value or "").strip() for value in runtime_pipeline_values if str(value or "").strip()})
    pipeline_key = ",".join(pipeline_parts) or (embedding_space or None)
    doc_ids = [str(document_id) for document_id in (document_ids or [])]

    cache_eligible = bool(cache_enabled)
    distributed_singleflight_eligible = bool(distributed_singleflight_enabled)
    semantic_cache_eligible = bool(semantic_cache_enabled) and not bool(semantic_cache_dataset_scoped)
    cache_meta: dict[str, Any] = {
        "enabled": bool(cache_eligible),
        "backend": "redis",
        "hit": False,
        "singleflight_enabled": bool(distributed_singleflight_eligible),
        "semantic": {
            "enabled": bool(semantic_cache_eligible),
            "backend": "milvus+redis",
            "hit": False,
        },
    }

    scope_failure_reason: str | None = None
    if document_scope_resolution_failed:
        scope_failure_reason = "missing_document_runtime"
    elif runtime_scope_ids and (runtime_shard_count <= 0 or runtime_scope_missing_dataset_ids):
        scope_failure_reason = "missing_dataset_runtime"

    if tenant_id is None:
        cache_eligible = False
        distributed_singleflight_eligible = False
        semantic_cache_eligible = False
        cache_meta["skip_reason"] = "missing_tenant"
        cache_meta["semantic"]["skip_reason"] = "missing_tenant"
    elif not account_id0:
        cache_eligible = False
        distributed_singleflight_eligible = False
        semantic_cache_eligible = False
        cache_meta["skip_reason"] = "missing_account"
        cache_meta["semantic"]["skip_reason"] = "missing_account"
    elif not document_ids and not dataset_scope_ids and not metadata_filter_dataset_scoped:
        cache_eligible = False
        distributed_singleflight_eligible = False
        semantic_cache_eligible = False
        cache_meta["skip_reason"] = "missing_scope"
        cache_meta["semantic"]["skip_reason"] = "missing_scope"
    elif scope_failure_reason is not None:
        cache_eligible = False
        distributed_singleflight_eligible = False
        semantic_cache_eligible = False
        cache_meta["skip_reason"] = scope_failure_reason
        cache_meta["semantic"]["skip_reason"] = scope_failure_reason
    elif runtime_shard_count > 1:
        semantic_cache_eligible = False
        cache_meta["semantic"]["skip_reason"] = "multi_runtime_scope"

    if cache_eligible and cache_ttl <= 0:
        cache_eligible = False
        cache_meta["skip_reason"] = "ttl_zero"

    if semantic_cache_eligible and semantic_cache_ttl <= 0:
        semantic_cache_eligible = False
        cache_meta["semantic"]["skip_reason"] = "ttl_zero"

    cache_meta["enabled"] = bool(cache_eligible)
    cache_meta["singleflight_enabled"] = bool(distributed_singleflight_eligible)
    cache_meta["semantic"]["enabled"] = bool(semantic_cache_eligible)

    return HybridCacheScopeDecision(
        account_id=account_id0,
        dataset_id=dataset_id0,
        pipeline_key=pipeline_key,
        document_ids=doc_ids,
        cache_eligible=cache_eligible,
        distributed_singleflight_eligible=distributed_singleflight_eligible,
        semantic_cache_eligible=semantic_cache_eligible,
        cache_meta=cache_meta,
        scope_failure_reason=scope_failure_reason,
    )
