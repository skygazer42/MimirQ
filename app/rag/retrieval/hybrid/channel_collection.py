"""Collect hybrid recall channels and their failures without reader-owned request state."""

import time
from dataclasses import dataclass, field, replace
from typing import Any

from app.core.database import SessionLocal
from app.core.stream_events import emit_stream_event
from app.rag.retrieval.corpus_index import CorpusIndex, CorpusScope, CorpusSearchResult
from app.rag.retrieval.hybrid import corpus_channels, lexical_search, vector_search
from app.rag.retrieval.hybrid.channel_health import RetrievalChannelHealth
from app.rag.retrieval.hybrid.channel_results import HybridChannelResults
from app.rag.retrieval.hybrid.common import (
    _log_retriever_fallback,
    _query_looks_like_cjk_metadata_anchor,
    _results_contain_metadata_exact_anchor,
    logger,
)
from app.rag.retrieval.hybrid.metadata_scope import collect_dataset_scope
from app.rag.retrieval.hybrid.runtime_scope import ResolvedRetrievalScope
from app.rag.retrieval.retriever_options import HybridSearchOptions
from app.services.rag_runtime_limiter import RetrievalAdmissionTimeoutError
from app.storage.bm25.milvus import BM25IndexNotReadyError
from app.storage.vector.factory import BaseVectorStore, get_vector_store


@dataclass(frozen=True)
class ChannelRequest:
    query: str
    options: HybridSearchOptions
    resolved_scope: ResolvedRetrievalScope

    @property
    def mode(self) -> str:
        return self.options.retrieval_mode.lower()

    @property
    def fetch_k(self) -> int:
        multiplier = max(1, self.options.mmr_fetch_k_multiplier) if self.mode == "mmr" else 2
        return self.options.top_k * multiplier

    @property
    def corpus_scope(self) -> CorpusScope:
        scope = self.resolved_scope.scope
        if scope.tenant_id is None:
            raise LookupError("Retrieval corpus requires tenant identity")
        datasets = () if scope.document_ids else scope.dataset_ids
        if not datasets and not scope.document_ids:
            datasets = tuple(sorted(collect_dataset_scope(self.resolved_scope.keyword_filter), key=str))
        return CorpusScope(scope.tenant_id, datasets, scope.document_ids)


@dataclass(frozen=True)
class ChannelPolicy:
    sparse: corpus_channels.SparseSearchPolicy
    native_hybrid_enabled: bool
    colbert_enabled: bool
    colpali_enabled: bool
    bm25_enabled: bool
    lexical_enabled: bool
    keyword_bm25_secondary_enabled: bool
    lexical_hybrid_fallback_only: bool
    lexical_metadata_exact_fallback_enabled: bool
    metadata_exact_db_enabled: bool
    pg_trgm_available: bool | None = None


@dataclass(frozen=True)
class ChannelPlan:
    vector: bool
    bm25: bool
    lexical: bool
    sparse: bool
    colpali: bool
    colpali_reason: str
    keyword_strategy: dict[str, Any] | None


@dataclass
class VectorRecall:
    records: list[dict[str, Any]] = field(default_factory=list)
    batch: vector_search.VectorSearchBatch | None = None
    colbert: corpus_channels.CorpusChannelOutcome | None = None
    failure: Exception | None = None
    admission_timeout: RetrievalAdmissionTimeoutError | None = None
    shard_failed: bool = False
    elapsed_ms: float = 0.0
    colbert_elapsed_ms: float = 0.0


@dataclass
class MetadataExactRecall:
    protected_records: list[dict[str, Any]] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    failure: Exception | None = None
    run_reason: str = "not_run"
    triggered: bool = False
    primary_has_anchor: bool = False


@dataclass
class KeywordRecall:
    bm25: CorpusSearchResult = field(default_factory=lambda: CorpusSearchResult([], {}))
    lexical: lexical_search.LexicalOutcome = field(default_factory=lambda: lexical_search.LexicalOutcome([], None))
    metadata_exact: MetadataExactRecall = field(default_factory=MetadataExactRecall)
    bm25_failure: Exception | None = None
    lexical_run_reason: str = "not_run"
    bm25_elapsed_ms: float = 0.0
    lexical_elapsed_ms: float = 0.0


@dataclass
class AuxiliaryRecall:
    sparse: corpus_channels.CorpusChannelOutcome
    colpali_records: list[dict[str, Any]] = field(default_factory=list)
    colpali_failure: Exception | None = None


@dataclass(frozen=True)
class ChannelCollection:
    plan: ChannelPlan
    vector: VectorRecall
    keyword: KeywordRecall
    auxiliary: AuxiliaryRecall
    health: RetrievalChannelHealth

    @property
    def channels(self) -> HybridChannelResults:
        return HybridChannelResults(
            self.vector.records,
            self.keyword.bm25.records,
            self.keyword.lexical.records,
            self.auxiliary.sparse.records,
            {},
        )

    @property
    def failure(self) -> RetrievalAdmissionTimeoutError | None:
        if any(
            (
                self.vector.records,
                self.keyword.bm25.records,
                self.keyword.lexical.records,
                self.auxiliary.sparse.records,
                self.auxiliary.colpali_records,
            )
        ):
            return None
        return self.vector.admission_timeout


def plan_channels(query: str, mode: str, policy: ChannelPolicy) -> ChannelPlan:
    colpali, colpali_reason = False, "COLPALI_RETRIEVAL_ENABLED=false"
    if policy.colpali_enabled:
        from app.rag.policy.modality_router import classify_query_modality

        try:
            modality, _reasons = classify_query_modality(query)
            colpali = modality == "image"
            colpali_reason = "image_query" if colpali else "disabled"
        except Exception as exc:
            _log_retriever_fallback("colpali_modality", exc)
            colpali_reason = "router_exception"
    keyword_mode = mode in ("hybrid", "keyword", "mmr")
    bm25 = keyword_mode
    keyword_strategy = None
    if mode == "keyword":
        bm25 = policy.keyword_bm25_secondary_enabled if policy.lexical_enabled else True
        keyword_strategy = {
            "primary": "lexical_db" if policy.lexical_enabled else "bm25",
            "secondary": "bm25" if policy.lexical_enabled and policy.keyword_bm25_secondary_enabled else None,
            "bm25_secondary_enabled": policy.lexical_enabled and policy.keyword_bm25_secondary_enabled,
            "lexical_db_enabled": policy.lexical_enabled,
            "bm25_index_enabled": policy.bm25_enabled,
        }
        if not policy.lexical_enabled:
            keyword_strategy["fallback_reason"] = "lexical_db_disabled"
    return ChannelPlan(
        vector=mode in ("hybrid", "vector", "mmr"),
        bm25=bm25 and policy.bm25_enabled,
        lexical=keyword_mode and policy.lexical_enabled,
        sparse=keyword_mode and policy.sparse.enabled,
        colpali=colpali,
        colpali_reason=colpali_reason,
        keyword_strategy=keyword_strategy,
    )


def collect_channels(
    request: ChannelRequest,
    *,
    policy: ChannelPolicy,
    corpus_index: CorpusIndex,
    vector_store: BaseVectorStore | None = None,
) -> ChannelCollection:
    """Run the supported recall/fallback sequence; every outcome belongs to this call."""
    return _ChannelCollector(request, policy=policy, corpus_index=corpus_index, vector_store=vector_store).collect()


class _ChannelCollector:
    def __init__(
        self,
        request: ChannelRequest,
        *,
        policy: ChannelPolicy,
        corpus_index: CorpusIndex,
        vector_store: BaseVectorStore | None,
    ) -> None:
        self.request = request
        self.policy = policy
        self.corpus_index = corpus_index
        self.vector_store = vector_store
        self.plan = plan_channels(request.query, request.mode, policy)
        self.vector = VectorRecall()
        self.keyword = KeywordRecall(lexical=lexical_search.LexicalOutcome([], policy.pg_trgm_available))
        self.auxiliary = AuxiliaryRecall(
            sparse=corpus_channels.CorpusChannelOutcome([], corpus_channels.skipped_sparse_status(policy.sparse))
        )
        self.health = RetrievalChannelHealth()

    def collect(self) -> ChannelCollection:
        emit_stream_event("event", {"message": "正在召回候选…"}, dedupe_key="retrieval.recall")
        if self.plan.vector:
            self._vector_search()
            if not self.vector.records and self.policy.colbert_enabled:
                self._colbert_search()
        if self.request.mode == "keyword":
            if self.plan.lexical:
                self._lexical_search("keyword_primary")
            if self.plan.bm25 or (not self.keyword.lexical.records and self.policy.bm25_enabled):
                self._bm25_search()
        else:
            if self.plan.bm25:
                self._bm25_search()
            self._hybrid_lexical_search()
        if self.plan.sparse:
            self._sparse_search()
        if self.plan.colpali:
            self._colpali_search()
        if self.request.mode == "vector" and (not self.vector.records or self.vector.shard_failed):
            self._bm25_search()
            self._lexical_search("vector_fallback")
        elif self.request.mode == "keyword" and not (
            self.keyword.bm25.records or self.keyword.lexical.records or self.auxiliary.sparse.records
        ):
            self._vector_search()
        return ChannelCollection(self.plan, self.vector, self.keyword, self.auxiliary, self.health)

    def _vector_search(self) -> None:
        self.health.started("vector")
        started = time.perf_counter()
        try:
            resolved = self.request.resolved_scope
            if resolved.runtime_dataset_ids and not resolved.runtime_shards:
                self.health.failed("vector", LookupError("MissingDatasetRuntime"))
                return
            metadata_filter = resolved.keyword_filter if resolved.runtime_shards else resolved.vector_filter
            batch = vector_search.search_vectors(
                vector_search.VectorSearchRequest(
                    self.request.query,
                    self.request.fetch_k,
                    self.request.options.score_threshold,
                    replace(resolved.scope, metadata_filter=metadata_filter),
                ),
                runtime=resolved.runtime,
                shards=resolved.runtime_shards,
                policy=vector_search.VectorSearchPolicy(
                    self.policy.sparse.enabled, self.policy.sparse.provider, self.policy.native_hybrid_enabled
                ),
                vector_store=self.vector_store if self.vector_store is not None else get_vector_store(),
            )
            self.vector.batch, self.vector.records = batch, batch.records
            self.vector.shard_failed = bool(batch.failures)
            for failure in batch.failures:
                self.health.failed("vector", failure)
                if self.vector.admission_timeout is None and isinstance(failure, RetrievalAdmissionTimeoutError):
                    self.vector.admission_timeout = failure
            if resolved.missing_dataset_ids:
                self.health.failed("vector", LookupError("MissingDatasetRuntime"))
                self.vector.shard_failed = True
            if batch.successful_shards:
                self.health.succeeded("vector")
        except Exception as exc:
            self.vector.failure = exc
            self.health.failed("vector", exc)
            logger.warning("Vector search failed: %s", exc)
            self.vector.records = []
        finally:
            self.vector.elapsed_ms += (time.perf_counter() - started) * 1000

    def _corpus_request(self) -> corpus_channels.CorpusChannelRequest:
        return corpus_channels.CorpusChannelRequest(
            self.request.query,
            self.request.fetch_k,
            self.request.corpus_scope,
            self.request.resolved_scope.keyword_filter,
        )

    def _colbert_search(self) -> None:
        self.health.started("colbert")
        started = time.perf_counter()
        try:
            result = corpus_channels.search_colbert(self._corpus_request(), corpus_index=self.corpus_index)
            self.vector.colbert = result
            if result.failure is not None:
                self.health.failed("colbert", result.failure)
                logger.warning("ColBERT ANN search failed: %s", result.failure)
            else:
                self.vector.records = result.records
                self.health.succeeded("colbert")
        except Exception as exc:
            self.vector.colbert = corpus_channels.CorpusChannelOutcome([], {}, exc)
            self.health.failed("colbert", exc)
            logger.warning("ColBERT ANN search failed: %s", exc)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            self.vector.elapsed_ms += elapsed_ms
            self.vector.colbert_elapsed_ms += elapsed_ms

    def _bm25_search(self) -> None:
        self.health.started("bm25")
        started = time.perf_counter()
        try:
            self.keyword.bm25 = self.corpus_index.search(
                self.request.query,
                scope=self.request.corpus_scope,
                top_k=self.request.fetch_k,
                metadata_filter=self.request.resolved_scope.keyword_filter,
            )
            self.health.succeeded("bm25")
        except BM25IndexNotReadyError:
            raise
        except Exception as exc:
            self.keyword.bm25_failure = exc
            self.health.failed("bm25", exc)
            logger.warning("BM25 search failed: %s", exc)
            self.keyword.bm25 = CorpusSearchResult([], {})
        finally:
            self.keyword.bm25_elapsed_ms += (time.perf_counter() - started) * 1000

    def _lexical_request(self) -> lexical_search.LexicalRequest:
        return lexical_search.LexicalRequest(
            self.request.query,
            self.request.fetch_k,
            replace(self.request.resolved_scope.scope, metadata_filter=self.request.resolved_scope.keyword_filter),
        )

    def _lexical_search(self, run_reason: str) -> None:
        self.health.started("lexical_db")
        started = time.perf_counter()
        try:
            with SessionLocal() as db:
                result = lexical_search.search_lexical(
                    db, self._lexical_request(), pg_trgm_available=self.keyword.lexical.pg_trgm_available
                )
            self.keyword.lexical = result
            if result.failure is not None:
                self.health.failed("lexical_db", result.failure)
                logger.warning("Lexical DB search failed: %s", result.failure)
            if result.failure is None or result.records:
                self.health.succeeded("lexical_db")
                self.keyword.lexical_run_reason = run_reason
            else:
                self.keyword.lexical_run_reason = "error"
        except Exception as exc:
            self.keyword.lexical = lexical_search.LexicalOutcome([], self.keyword.lexical.pg_trgm_available, exc)
            self.keyword.lexical_run_reason = "error"
            self.health.failed("lexical_db", exc)
            logger.warning("Lexical DB search failed: %s", exc)
        finally:
            self.keyword.lexical_elapsed_ms += (time.perf_counter() - started) * 1000

    def _hybrid_lexical_search(self) -> None:
        metadata_exact = self.keyword.metadata_exact
        anchor_like = self.policy.lexical_metadata_exact_fallback_enabled and _query_looks_like_cjk_metadata_anchor(
            self.request.query
        )
        primary = self.vector.records + self.keyword.bm25.records
        if anchor_like:
            metadata_exact.primary_has_anchor = _results_contain_metadata_exact_anchor(
                self.request.query, primary, limit=max(1, self.request.options.top_k)
            )
        metadata_exact.triggered = self.policy.lexical_hybrid_fallback_only and anchor_like
        if self.plan.lexical:
            if (
                not self.policy.lexical_hybrid_fallback_only
                or len(primary) < max(1, self.request.options.top_k)
                or metadata_exact.triggered
            ):
                reason = (
                    "hybrid_parallel"
                    if not self.policy.lexical_hybrid_fallback_only
                    else ("hybrid_metadata_exact_fallback" if metadata_exact.triggered else "hybrid_fallback")
                )
                self._lexical_search(reason)
            else:
                self.keyword.lexical_run_reason = "skipped_primary_candidates_sufficient"
        if self.policy.metadata_exact_db_enabled and metadata_exact.triggered:
            self._metadata_exact_search()
        elif not self.policy.metadata_exact_db_enabled:
            metadata_exact.run_reason = "disabled"

    def _metadata_exact_search(self) -> None:
        metadata_exact = self.keyword.metadata_exact
        lexical_has_anchor = _results_contain_metadata_exact_anchor(
            self.request.query, self.keyword.lexical.records, limit=max(1, self.request.options.top_k)
        )
        started = time.perf_counter()
        try:
            with SessionLocal() as db:
                result = lexical_search.search_metadata_exact(db, self._lexical_request(), enabled=True)
            metadata_exact.failure = result.failure
            metadata_exact.records = result.records
            metadata_exact.run_reason = (
                "error"
                if result.failure is not None
                else (
                    "hybrid_metadata_exact_fallback_enrich" if lexical_has_anchor else "hybrid_metadata_exact_fallback"
                )
            )
            if result.failure is not None:
                logger.debug("Metadata exact DB fallback failed: %s", result.failure)
            self._append_metadata_exact_results(result.records)
        except Exception as exc:
            metadata_exact.failure, metadata_exact.run_reason = exc, "error"
            logger.debug("Metadata exact DB fallback failed: %s", exc)
        finally:
            self.keyword.lexical_elapsed_ms += (time.perf_counter() - started) * 1000

    def _append_metadata_exact_results(self, records: list[dict[str, Any]]) -> None:
        lexical_records = self.keyword.lexical.records
        seen = {
            str((item.get("metadata") or {}).get("chunk_id") or item.get("chunk_id") or "") for item in lexical_records
        }
        for item in records:
            chunk_id = str((item.get("metadata") or {}).get("chunk_id") or item.get("chunk_id") or "")
            if chunk_id and chunk_id in seen:
                continue
            if chunk_id:
                seen.add(chunk_id)
            lexical_records.append(item)
            self.keyword.metadata_exact.protected_records.append(item)

    def _sparse_search(self) -> None:
        self.health.started("sparse")
        try:
            result = corpus_channels.search_sparse(
                self._corpus_request(), corpus_index=self.corpus_index, policy=self.policy.sparse
            )
        except Exception as exc:
            result = corpus_channels.CorpusChannelOutcome(
                [], {**self.auxiliary.sparse.status, "outcome": "error", "reason": "exception", "candidates": 0}, exc
            )
        self.auxiliary.sparse = result
        if result.failure is not None:
            self.health.failed("sparse", result.failure)
            logger.warning("Sparse search failed: %s", result.failure)
        else:
            self.health.succeeded("sparse")

    def _colpali_search(self) -> None:
        self.health.started("colpali")
        visual_filter = {
            "$or": [{"visual_parser": "colpali"}, {"content_type": "visual_document"}, {"doc_type_kwd": "image"}]
        }
        metadata_filter = self.request.resolved_scope.keyword_filter
        if metadata_filter:
            visual_filter = {"$and": [metadata_filter, visual_filter]}
        try:
            result = self.corpus_index.search(
                self.request.query,
                scope=self.request.corpus_scope,
                top_k=self.request.fetch_k,
                metadata_filter=visual_filter,
            )
            for row in result.records:
                item = dict(row)
                score = float(item.get("score", 0.0))
                item["metadata"] = {**item.get("metadata", {}), "colpali_score": score}
                item["metadata"].setdefault("visual_parser", "colpali")
                item.update(colpali_score=score, lexical_score=score, hit_type="colpali_retriever")
                self.auxiliary.colpali_records.append(item)
            self.health.succeeded("colpali")
        except Exception as exc:
            self.auxiliary.colpali_failure = exc
            self.health.failed("colpali", exc)
            logger.warning("ColPali retriever failed: %s", exc)
