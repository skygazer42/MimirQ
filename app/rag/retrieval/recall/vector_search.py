"""Execute scoped vector queries and return records and failures per shard."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Any

from app.infrastructure.config import settings
from app.rag.retrieval.recall.common import _RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY, logger
from app.rag.retrieval.recall.results import top_scored_results
from app.rag.retrieval.recall.runtime_scope import RetrievalScope, RuntimeShard, build_vector_filter
from app.services.datasets.embedding_config import DatasetEmbeddingRuntimeConfig, create_embeddings_for_runtime
from app.services.runtime.retrieval_limiter import run_with_retrieval_backend_budget_sync
from app.storage.vector.factory import BaseVectorStore
from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name


@dataclass(frozen=True)
class VectorSearchRequest:
    query: str
    top_k: int
    score_threshold: float
    scope: RetrievalScope


@dataclass(frozen=True)
class VectorShardResult:
    shard: RuntimeShard
    records: list[dict[str, Any]]
    failure: Exception | None


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


def search_dataset_vectors(
    request: VectorSearchRequest, *, runtime: DatasetEmbeddingRuntimeConfig
) -> list[dict[str, Any]]:
    query_vector = create_embeddings_for_runtime(runtime).embed_query(request.query)
    scoped_filter = dict(request.scope.metadata_filter or {})
    if request.scope.tenant_id is not None:
        scoped_filter.setdefault("tenant_id", str(request.scope.tenant_id))
    if request.scope.document_ids:
        scoped_filter["document_id"] = {"$in": [str(document_id) for document_id in request.scope.document_ids]}
    adapter = get_milvus_adapter(resolve_collection_name(runtime.collection_name))
    records = adapter.search(
        query_vector=query_vector,
        top_k=max(1, request.top_k * 2),
        metadata_filter=scoped_filter,
    )
    filtered = [record for record in records if float(record.get("score") or 0.0) >= request.score_threshold]
    return filtered[: request.top_k]


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
    vector_store: BaseVectorStore,
) -> VectorSearchBatch:
    def execute(shard: RuntimeShard) -> VectorShardResult:
        try:
            shard_filter = build_vector_filter(
                request.scope.metadata_filter,
                embedding_space=shard.runtime.embedding_space_hash,
                dataset_ids=shard.dataset_ids,
            )
            if shard.runtime.dataset_scoped:
                result = search_dataset_vectors(
                    replace(request, scope=replace(request.scope, metadata_filter=shard_filter)),
                    runtime=shard.runtime,
                )
                records = result
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
            )
        except Exception as exc:
            logger.warning("Vector search shard failed for collection %s: %s", shard.runtime.collection_name, exc)
            return VectorShardResult(shard=shard, records=[], failure=exc)

    def search(shard: RuntimeShard) -> VectorShardResult:
        try:
            return run_with_retrieval_backend_budget_sync(execute, shard)
        except Exception as exc:
            logger.warning(
                "Vector search shard admission failed for collection %s: %s", shard.runtime.collection_name, exc
            )
            return VectorShardResult(shard=shard, records=[], failure=exc)

    max_workers = min(len(shards), max(1, settings.RAG_VECTOR_SHARD_MAX_CONCURRENCY))
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
    vector_store: BaseVectorStore,
) -> VectorSearchBatch:
    if shards:
        return search_runtime_shards(request, shards=shards, vector_store=vector_store)
    if runtime.dataset_scoped:
        result = search_dataset_vectors(request, runtime=runtime)
        records = tag_expected_space(result, expected_space=runtime.embedding_space_hash)
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
    outcome = VectorShardResult(shard=RuntimeShard(runtime, ()), records=records, failure=None)
    return VectorSearchBatch(records=records, shards=(outcome,))
