"""Own candidate merge, reranking and diversity with diagnostics scoped to this call."""

import time
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.stream_events import emit_stream_event
from app.rag.core.filters import match_metadata_filter
from app.rag.reranker.factory import get_reranker
from app.rag.reranker.types import RerankCandidate
from app.rag.retrieval.corpus_index import CorpusIndex
from app.rag.retrieval.hybrid.channel_collection import ChannelCollection, ChannelRequest
from app.rag.retrieval.hybrid.channel_results import HybridChannelResults, prepare_hybrid_channel_results
from app.rag.retrieval.hybrid.common import _apply_metadata_exact_anchor_to_result, logger
from app.rag.retrieval.hybrid.dedup import DedupDiversityMixin
from app.rag.retrieval.hybrid.fusion import FusionMixin
from app.rag.retrieval.hybrid.metadata_ordering import order_metadata_anchors
from app.rag.retrieval.hybrid.text_preparation import rerank_text_from_result
from app.rag.retrieval.retriever_policy import RetrievalPolicyMixin


@dataclass(frozen=True)
class FusionPolicy:
    strategy: str
    rrf_k: int
    budgets: dict[str, int] | None = None
    min_scores: dict[str, float] | None = None
    weights: dict[str, float] | None = None


@dataclass(frozen=True)
class DedupPolicy:
    enabled: bool
    jaccard_threshold: float
    max_compare: int
    max_chunks_per_record_identity: int


@dataclass(frozen=True)
class DiversityPolicy:
    max_chunks_per_doc: int
    max_chunks_per_page: int
    min_distinct_docs: int


@dataclass(frozen=True)
class RerankPolicy:
    enabled: bool
    provider: str
    top_n: int


@dataclass(frozen=True)
class RankingPolicy:
    fusion: FusionPolicy
    dedup: DedupPolicy
    diversity: DiversityPolicy
    rerank: RerankPolicy


@dataclass(frozen=True)
class RankedCandidates:
    records: list[dict[str, Any]]
    channels: HybridChannelResults
    metrics: dict[str, Any]
    diversity: dict[str, Any]
    fusion_elapsed_ms: float
    rerank_failure: Exception | None


def rank_candidates(
    request: ChannelRequest,
    collection: ChannelCollection,
    *,
    policy: RankingPolicy,
    corpus_index: CorpusIndex,
) -> RankedCandidates:
    return _RankingRun(request, policy=policy).rank(collection, corpus_index=corpus_index)


class _RankingRun(DedupDiversityMixin, FusionMixin, RetrievalPolicyMixin):
    """One operation's algorithm configuration and diagnostics; never shared by requests."""

    _bm25_tokenize = staticmethod(CorpusIndex._bm25_tokenize)
    _rerank_text_from_result = staticmethod(rerank_text_from_result)

    def __init__(self, request: ChannelRequest, *, policy: RankingPolicy) -> None:
        self.request, self.policy = request, policy
        self.k = request.options.top_k
        self.tenant_id = request.resolved_scope.scope.tenant_id
        self.fusion_strategy = policy.fusion.strategy
        self.rrf_k = policy.fusion.rrf_k
        self.fusion_budgets, self.fusion_min_scores, self.fusion_weights = (
            policy.fusion.budgets,
            policy.fusion.min_scores,
            policy.fusion.weights,
        )
        self.dedup_enabled = policy.dedup.enabled
        self.dedup_jaccard_threshold, self.dedup_max_compare = policy.dedup.jaccard_threshold, policy.dedup.max_compare
        self.max_chunks_per_record_identity = policy.dedup.max_chunks_per_record_identity
        self.max_chunks_per_doc, self.max_chunks_per_page, self.min_distinct_docs = (
            policy.diversity.max_chunks_per_doc,
            policy.diversity.max_chunks_per_page,
            policy.diversity.min_distinct_docs,
        )
        self.enable_reranker, self.reranker_provider, self.reranker_top_n = (
            policy.rerank.enabled,
            policy.rerank.provider,
            policy.rerank.top_n,
        )
        self.metrics: dict[str, Any] = {}
        # Existing algorithms write to this request-owned dictionary, returned in RankedCandidates.
        self._last_channel_metrics = self.metrics
        self.rerank_failure: Exception | None = None

    def rank(self, collection: ChannelCollection, *, corpus_index: CorpusIndex) -> RankedCandidates:
        request, options = self.request, self.request.options
        resolved = request.resolved_scope
        raw = collection.channels
        channels = prepare_hybrid_channel_results(
            query=request.query,
            vector_results=raw.vector_results,
            bm25_results=raw.bm25_results,
            lexical_results=raw.lexical_results,
            sparse_results=raw.sparse_results,
            document_ids=list(resolved.scope.document_ids),
            vector_filter=resolved.vector_filter,
            runtime_shards_present=bool(resolved.runtime_shards),
            chunk_id_lookup=corpus_index.chunk_id_lookup(request.corpus_scope),
            match_metadata_filter=match_metadata_filter,
            metadata_exact_pre_fusion_enabled=settings.RETRIEVAL_METADATA_EXACT_PRE_FUSION_ENABLED,
            phrase_boost_weight=max(0.0, settings.RETRIEVAL_EXACT_PHRASE_RERANK_BOOST),
        )
        started = time.perf_counter()
        records = self._merge_results(
            channels.vector_results,
            channels.bm25_results,
            channels.lexical_results + collection.auxiliary.colpali_records,
            channels.sparse_results,
            query=request.query,
            alpha=options.alpha,
            fusion_strategy=self.fusion_strategy,
            rrf_k=self.rrf_k,
            top_k=options.top_k,
        )
        records = self._append_protected(records, collection, before_diversity=True)
        self.metrics["merged_pre_dedup"] = len(records)
        pre_ordering: dict[str, Any] = {}
        records = order_metadata_anchors(request.query, records, stats=pre_ordering)
        if pre_ordering:
            self.metrics["metadata_exact_pre_dedup_ordering"] = pre_ordering
        records = self._deduplicate_results(records)
        self.metrics["merged_post_dedup"] = len(records)
        fusion_elapsed_ms = (time.perf_counter() - started) * 1000
        records = self._apply_hybrid_rerank_stack(records)
        self.metrics["merged_post_rerank"] = len(records)
        self.metrics["attribution"] = self._hybrid_result_attribution(records)
        before_diversity = len(records)
        diversity: dict[str, Any] = {}
        records = self._apply_document_diversity(records, top_k=options.top_k, stats=diversity)
        records = self._append_protected(records, collection, before_diversity=False)
        self.metrics["diversity"] = {
            "before": before_diversity,
            "after": len(records),
            "dropped": max(0, before_diversity - len(records)),
        }
        self.metrics["returned_top_k"] = min(options.top_k, len(records))
        final_ordering: dict[str, Any] = {}
        records = order_metadata_anchors(request.query, records, stats=final_ordering)
        if final_ordering:
            self.metrics["metadata_exact_final_ordering"] = final_ordering
        return RankedCandidates(records, channels, self.metrics, diversity, fusion_elapsed_ms, self.rerank_failure)

    def _append_protected(
        self, records: list[dict[str, Any]], collection: ChannelCollection, *, before_diversity: bool
    ) -> list[dict[str, Any]]:
        existing = {self._result_key(item) for item in records}
        added = 0
        for item in collection.keyword.metadata_exact.protected_records:
            key = self._result_key(item)
            if key in existing:
                continue
            existing.add(key)
            records.append(dict(item))
            added += 1
        if added:
            name = "protected_added" if before_diversity else "protected_after_diversity_added"
            self.metrics.setdefault("metadata_exact_db", {})[name] = added
        return records

    def _set_channel_metric(self, key: str, value: Any) -> None:
        self.metrics[key] = value

    def _apply_hybrid_rerank_stack(
        self,
        merged_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if merged_results:
            emit_stream_event("event", {"message": "候选召回完成，正在重排…"}, dedupe_key="retrieval.rerank")
        if self.request.mode == "mmr" and merged_results:
            merged_results = self._mmr_rerank(
                merged_results,
                query=self.request.query,
                top_k=self.request.options.top_k,
                lambda_mult=self.request.options.mmr_lambda,
            )
        elif self.request.options.enable_weight_rerank and merged_results:
            merged_results = self._weight_rerank(
                query=self.request.query,
                documents=merged_results,
                vector_weight=self.request.options.vector_weight,
                keyword_weight=self.request.options.keyword_weight,
            )
        if merged_results and bool(self.enable_reranker):
            merged_results = self._apply_optional_llm_reranker(merged_results)
        return merged_results

    def _apply_optional_llm_reranker(
        self,
        merged_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rerank_meta: dict[str, Any] = {
            "enabled": True,
            "provider": None,
            "top_n_config": int(self.reranker_top_n or 0),
            "candidates_n": 0,
            "used": False,
            "elapsed_sec": 0.0,
            "model_used": None,
            "error": None,
            "skip_reason": None,
            "skip_top_score": None,
            "skip_score_gap": None,
        }
        provider = (self.reranker_provider or settings.RERANKER_PROVIDER or "llm").lower()
        rerank_meta["provider"] = provider
        if provider in ("none", "off", "false", "0"):
            rerank_meta["skip_reason"] = "provider_off"
            self._set_channel_metric("rerank", rerank_meta)
            return merged_results
        final_k = max(
            1,
            int(self.request.options.requested_k)
            if self.request.options.requested_k is not None
            else int(self.request.options.top_k or 0),
        )
        candidates_n = max(int(self.reranker_top_n or settings.RERANKER_TOP_N or 20), final_k)
        candidates_n = min(candidates_n, len(merged_results))
        rerank_meta["candidates_n"] = int(candidates_n)
        conditional_rerank_enabled = settings.RERANK_CONDITIONAL_ENABLED
        top_score = float(merged_results[0].get("score", 0.0) or 0.0)
        second_score = float(merged_results[1].get("score", 0.0) or 0.0) if len(merged_results) > 1 else 0.0
        score_gap = top_score - second_score
        rerank_meta["skip_top_score"] = round(float(top_score), 6)
        rerank_meta["skip_score_gap"] = round(float(score_gap), 6)
        skip_threshold = float(settings.RERANK_SKIP_THRESHOLD or 0.85)
        skip_gap = float(settings.RERANK_SKIP_GAP or 0.15)
        if conditional_rerank_enabled and top_score >= skip_threshold and score_gap >= skip_gap:
            rerank_meta["skip_reason"] = "high_confidence"
            self._set_channel_metric("rerank", rerank_meta)
            self._set_channel_metric("merged_post_rerank", len(merged_results or []))
            return merged_results
        merged_results = self._run_llm_reranker(
            query=self.request.query,
            merged_results=merged_results,
            candidates_n=candidates_n,
            provider=provider,
            rerank_meta=rerank_meta,
        )
        self._set_channel_metric("rerank", rerank_meta)
        return merged_results

    def _run_llm_reranker(
        self,
        *,
        query: str,
        merged_results: list[dict[str, Any]],
        candidates_n: int,
        provider: str,
        rerank_meta: dict[str, Any],
    ) -> list[dict[str, Any]]:
        reranker = get_reranker(provider)
        candidates: list[RerankCandidate] = []
        id_to_doc: dict[str, dict[str, Any]] = {}
        for doc in merged_results[:candidates_n]:
            rid = self._result_key(doc)
            text = self._rerank_text_from_result(doc)
            if not rid or not text:
                continue
            meta = dict(doc.get("metadata") or {})
            meta["score"] = float(doc.get("score", 0.0) or 0.0)
            candidates.append(RerankCandidate(id=rid, text=text, metadata=meta))
            id_to_doc[rid] = doc
        if not candidates:
            rerank_meta["skip_reason"] = "no_candidates"
            return merged_results
        try:
            start = time.time()
            result = reranker.rerank(
                query=query,
                candidates=candidates,
                top_n=candidates_n,
                tenant_id=str(self.tenant_id or "").strip() or None,
                query_type=None,
            )
            rerank_elapsed = result.elapsed_sec or (time.time() - start)
            rerank_provider = result.provider or provider
            rerank_meta["used"] = True
            rerank_meta["elapsed_sec"] = round(float(rerank_elapsed), 3)
            rerank_meta["model_used"] = result.model_used
            rerank_meta["provider"] = rerank_provider
            ordered = self._reranked_documents(
                query=query,
                merged_results=merged_results,
                candidates_n=candidates_n,
                id_to_doc=id_to_doc,
                ordered_ids=result.ordered_ids,
                score_map=result.score_map,
                rerank_provider=rerank_provider,
                rerank_elapsed=rerank_elapsed,
                model_used=result.model_used,
                rerank_meta=rerank_meta,
            )
            return ordered + merged_results[candidates_n:]
        except Exception as exc:
            self.rerank_failure = exc
            rerank_meta["used"] = False
            rerank_meta["error"] = str(exc)[:200]
            rerank_meta["skip_reason"] = "error"
            logger.warning("Reranker failed (%s): %s", provider, exc)
            for doc in merged_results[:candidates_n]:
                meta = dict(doc.get("metadata") or {})
                meta.setdefault("reranker_provider", provider)
                meta.setdefault("reranker_error", str(exc)[:200])
                doc["metadata"] = meta
            return merged_results

    def _reranked_documents(
        self,
        *,
        query: str,
        merged_results: list[dict[str, Any]],
        candidates_n: int,
        id_to_doc: dict[str, dict[str, Any]],
        ordered_ids: list[str],
        score_map: dict[str, float],
        rerank_provider: str,
        rerank_elapsed: float,
        model_used: str | None,
        rerank_meta: dict[str, Any],
    ) -> list[dict[str, Any]]:
        ordered: list[dict[str, Any]] = []
        used: set[str] = set()
        boosted_after_rerank = 0
        phrase_boost_weight = max(
            0.0,
            float(settings.RETRIEVAL_EXACT_PHRASE_RERANK_BOOST or 0.0),
        )
        for rid in ordered_ids:
            doc = id_to_doc.get(rid)
            if not doc or rid in used:
                continue
            used.add(rid)
            new_doc = dict(doc)
            new_doc["retrieval_score"] = float(new_doc.get("score", 0.0) or 0.0)
            if rid in score_map:
                rerank_score = float(score_map[rid])
                new_doc["rerank_score"] = rerank_score
                phrase_boost = float(new_doc.get("exact_phrase_boost") or 0.0)
                metadata_boost = 0.0
                if _apply_metadata_exact_anchor_to_result(
                    query=query,
                    result=new_doc,
                    phrase_boost_weight=phrase_boost_weight,
                ):
                    metadata_boost = float(new_doc.get("metadata_exact_match_boost") or 0.0)
                final_score = min(1.0, float(rerank_score) + float(phrase_boost) + float(metadata_boost))
                new_doc["score"] = float(final_score)
                if phrase_boost > 0.0 or metadata_boost > 0.0:
                    new_doc["rerank_score_final"] = float(final_score)
                    boosted_after_rerank += 1
            new_doc["reranker_provider"] = rerank_provider
            new_doc["rerank_elapsed_sec"] = round(float(rerank_elapsed), 3)
            new_doc["rerank_model_used"] = model_used
            ordered.append(new_doc)
        if boosted_after_rerank > 0:
            ordered = sorted(ordered, key=lambda item: (-float(item.get("score", 0.0) or 0.0), self._result_key(item)))
            rerank_meta["post_rerank_exact_boosted"] = int(boosted_after_rerank)
        for doc in merged_results[:candidates_n]:
            rid = self._result_key(doc)
            if rid in used:
                continue
            new_doc = dict(doc)
            new_doc.setdefault("reranker_provider", rerank_provider)
            new_doc.setdefault("rerank_elapsed_sec", round(float(rerank_elapsed), 3))
            new_doc.setdefault("rerank_model_used", model_used)
            ordered.append(new_doc)
        return ordered

    @staticmethod
    def _hybrid_result_attribution(merged_results: list[dict[str, Any]]) -> dict[str, int]:
        attribution = {"vector": 0, "bm25": 0, "lexical_db": 0, "multi": 0}
        for doc in merged_results or []:
            has_v = float(doc.get("vector_score", 0.0) or 0.0) > 0.0
            has_b = float(doc.get("bm25_score", 0.0) or 0.0) > 0.0
            has_l = float(doc.get("lexical_score", 0.0) or 0.0) > 0.0
            n = int(has_v) + int(has_b) + int(has_l)
            if has_v:
                attribution["vector"] += 1
            if has_b:
                attribution["bm25"] += 1
            if has_l:
                attribution["lexical_db"] += 1
            if n > 1:
                attribution["multi"] += 1
        return attribution
