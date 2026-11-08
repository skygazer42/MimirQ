"""Vector shard execution with call-local results and native-hybrid diagnostics."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.rag.retrieval.hybrid.common import _RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY, _log_retriever_fallback, logger
from app.rag.retrieval.hybrid.result_values import top_scored_results
from app.rag.retrieval.hybrid.runtime_scope import RetrievalScope, RuntimeShard, build_vector_filter
from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig, create_embeddings_for_runtime
from app.services.rag_runtime_limiter import run_with_retrieval_backend_budget_sync
from app.storage.vector.factory import BaseVectorStore
from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name

if TYPE_CHECKING:
    from app.rag.retrieval.sparse import SparseVector


@dataclass(frozen=True)
class VectorSearchRequest:
    query: str
    top_k: int
    score_threshold: float
    scope: RetrievalScope


@dataclass(frozen=True)
class VectorSearchPolicy:
    sparse_enabled: bool
    sparse_provider: str
    native_hybrid_enabled: bool


@dataclass(frozen=True)
class NativeHybridOutcome:
    enabled: bool
    used: bool
    fallback_reason: str | None
    provider: str | None = None

    def as_debug(self) -> dict[str, Any]:
        result = {"enabled": self.enabled, "used": self.used, "fallback_reason": self.fallback_reason}
        if self.provider is not None:
            result["provider"] = self.provider
        return result


@dataclass(frozen=True)
class DatasetVectorResult:
    records: list[dict[str, Any]]
    native_hybrid: NativeHybridOutcome


@dataclass(frozen=True)
class VectorShardResult:
    shard: RuntimeShard
    records: list[dict[str, Any]]
    failure: Exception | None
    native_hybrid: NativeHybridOutcome | None


@dataclass(frozen=True)
class VectorSearchBatch:
    records: list[dict[str, Any]]
    shards: tuple[VectorShardResult, ...]

    @property
    def failures(self) -> tuple[Exception, ...]:
        return tuple(outcome.failure for outcome in self.shards if outcome.failure is not None)

    @property
    def successful_shards(self) -> int:
        return sum(outcome.failure is None for outcome in self.shards)


def _native_sparse_query(query: str, policy: VectorSearchPolicy) -> tuple["SparseVector", str]:
    from app.rag.retrieval.sparse import get_sparse_encoder, parse_synonyms, resolve_sparse_provider_capability

    capability = resolve_sparse_provider_capability(
        requested_provider=policy.sparse_provider, sparse_enabled=True, default_provider="deterministic"
    )
    provider = (
        str(capability.get("effective_provider") or policy.sparse_provider or "deterministic").strip().lower()
        or "deterministic"
    )
    encoder = get_sparse_encoder(
        provider=provider,
        synonyms=parse_synonyms(settings.SPARSE_RETRIEVAL_SYNONYMS),
        synonyms_raw=settings.SPARSE_RETRIEVAL_SYNONYMS,
    )
    return encoder.encode_batch([query])[0], provider


def search_dataset_vectors(
    request: VectorSearchRequest, *, runtime: DatasetEmbeddingRuntimeConfig, policy: VectorSearchPolicy
) -> DatasetVectorResult:
    query_vector = create_embeddings_for_runtime(runtime).embed_query(request.query)
    scoped_filter = dict(request.scope.metadata_filter or {})
    if request.scope.tenant_id is not None:
        scoped_filter.setdefault("tenant_id", str(request.scope.tenant_id))
    if request.scope.document_ids:
        scoped_filter["document_id"] = {"$in": [str(document_id) for document_id in request.scope.document_ids]}
    adapter = get_milvus_adapter(resolve_collection_name(runtime.collection_name))
    can_try_native = (
        policy.native_hybrid_enabled and settings.VECTOR_BACKEND.strip().lower() == "milvus" and policy.sparse_enabled
    )
    outcome = NativeHybridOutcome(enabled=policy.native_hybrid_enabled, used=False, fallback_reason=None)
    records = []
    if can_try_native:
        try:
            sparse_query, provider = _native_sparse_query(request.query, policy)
            if not sparse_query.weights:
                outcome = replace(outcome, fallback_reason="sparse_query_empty")
            else:
                records = adapter.search_native_hybrid(
                    query_vector=query_vector,
                    sparse_query_vector=sparse_query,
                    top_k=max(1, request.top_k * 2),
                    metadata_filter=(scoped_filter),
                )
                outcome = replace(outcome, used=True, provider=provider)
        except NotImplementedError:
            outcome = replace(outcome, fallback_reason="unsupported")
        except Exception as exc:
            _log_retriever_fallback("_search_dataset_scoped_vectors", exc)
            outcome = replace(outcome, fallback_reason=f"error:{exc.__class__.__name__}")
    if not records:
        records = adapter.search(
            query_vector=query_vector,
            top_k=max(1, request.top_k * 2),
            metadata_filter=(scoped_filter),
        )
        if can_try_native and outcome.fallback_reason is None:
            outcome = replace(outcome, fallback_reason="empty_result_fallback")
    filtered = [record for record in records if float(record.get("score") or 0.0) >= request.score_threshold]
    return DatasetVectorResult(records=filtered[: request.top_k], native_hybrid=outcome)


def tag_expected_space(records: list[dict[str, Any]], *, expected_space: str) -> list[dict[str, Any]]:
    tagged = []
    for record in records:
        metadata = dict(record.get("metadata") or {})
        if expected_space:
            metadata[_RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY] = expected_space
        tagged.append({**record, "metadata": metadata})
    return tagged


def search_runtime_shards(
    request: VectorSearchRequest,
    *,
    shards: tuple[RuntimeShard, ...],
    policy: VectorSearchPolicy,
    vector_store: BaseVectorStore,
) -> VectorSearchBatch:
    def execute(shard: RuntimeShard) -> VectorShardResult:
        try:
            shard_filter = build_vector_filter(
                request.scope.metadata_filter,
                embedding_space=shard.runtime.embedding_space_hash,
                dataset_ids=shard.dataset_ids,
            )
            native_hybrid = None
            if shard.runtime.dataset_scoped:
                result = search_dataset_vectors(
                    replace(request, scope=replace(request.scope, metadata_filter=shard_filter)),
                    runtime=shard.runtime,
                    policy=policy,
                )
                records, native_hybrid = result.records, result.native_hybrid
            else:
                records = vector_store.search(
                    query=request.query,
                    top_k=request.top_k,
                    score_threshold=request.score_threshold,
                    document_ids=list(request.scope.document_ids) if request.scope.document_ids else None,
                    tenant_id=request.scope.tenant_id,
                    metadata_filter=shard_filter,
                )
            return VectorShardResult(
                shard=shard,
                records=tag_expected_space(records, expected_space=shard.runtime.embedding_space_hash),
                failure=None,
                native_hybrid=native_hybrid,
            )
        except Exception as exc:
            logger.warning("Vector search shard failed for collection %s: %s", shard.runtime.collection_name, exc)
            return VectorShardResult(shard=shard, records=[], failure=exc, native_hybrid=None)

    def search(shard: RuntimeShard) -> VectorShardResult:
        try:
            return run_with_retrieval_backend_budget_sync(execute, shard)
        except Exception as exc:
            logger.warning(
                "Vector search shard admission failed for collection %s: %s", shard.runtime.collection_name, exc
            )
            return VectorShardResult(shard=shard, records=[], failure=exc, native_hybrid=None)

    max_workers = min(len(shards), max(1, settings.RAG_VECTOR_SHARD_MAX_CONCURRENCY or 1))
    if max_workers <= 1:
        outcomes = tuple(search(shard) for shard in shards)
    else:
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="rag-vector-shard") as executor:
            outcomes = tuple(executor.map(search, shards))
    records = [record for outcome in outcomes for record in outcome.records]
    return VectorSearchBatch(records=top_scored_results(records, request.top_k), shards=outcomes)


def search_vectors(
    request: VectorSearchRequest,
    *,
    runtime: DatasetEmbeddingRuntimeConfig,
    shards: tuple[RuntimeShard, ...],
    policy: VectorSearchPolicy,
    vector_store: BaseVectorStore,
) -> VectorSearchBatch:
    if shards:
        return search_runtime_shards(request, shards=shards, policy=policy, vector_store=vector_store)
    if runtime.dataset_scoped:
        result = search_dataset_vectors(request, runtime=runtime, policy=policy)
        records = tag_expected_space(result.records, expected_space=runtime.embedding_space_hash)
        native_hybrid = result.native_hybrid
    else:
        parameters = {
            "query": request.query,
            "top_k": request.top_k,
            "score_threshold": request.score_threshold,
            "document_ids": list(request.scope.document_ids) if request.scope.document_ids else None,
            "tenant_id": request.scope.tenant_id,
        }
        if request.scope.metadata_filter:
            parameters["metadata_filter"] = request.scope.metadata_filter
        records = vector_store.search(**parameters)
        native_hybrid = None
    outcome = VectorShardResult(
        shard=RuntimeShard(runtime, ()), records=records, failure=None, native_hybrid=native_hybrid
    )
    return VectorSearchBatch(records=records, shards=(outcome,))
