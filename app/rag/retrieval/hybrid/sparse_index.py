"""SPLADE-style sparse index build/search for the hybrid retriever.

Split out of ``app.rag.retriever`` (see ``app.rag.retrieval.hybrid``). The
methods below run on the ``HybridRetriever`` instance via mixin inheritance.
"""

import hashlib
import threading
import time
from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.retrieval.hybrid.common import (
    NON_CRITICAL_RETRIEVER_FALLBACK_LOG,
    SPARSE_INDEX_DIR_FALLBACK,
    _log_retriever_fallback,
    logger,
)
from app.rag.retrieval.sparse import SparseVector


class SparseIndexMixin:
    """Sparse (SPLADE-style) vector index: build, persist, incremental upsert, and search."""

    def _get_sparse_build_lock(self, cache_key: str) -> threading.Lock:
        return self._sparse_build_locks.setdefault(cache_key, threading.Lock())

    def _sparse_provider_name(self) -> str:
        return str(self.sparse_provider or "deterministic").strip().lower()

    @staticmethod
    def _resolve_sparse_runtime(
        *,
        provider: str,
        build_sparse_provider_config: Any,
        get_sparse_encoder: Any,
        parse_synonyms: Any,
    ) -> tuple[dict[str, Any], Any]:
        synonyms_raw = str(getattr(settings, "SPARSE_RETRIEVAL_SYNONYMS", "") or "")
        synonyms = parse_synonyms(synonyms_raw) if synonyms_raw.strip() else {}
        provider_config = build_sparse_provider_config(
            provider=provider,
            synonyms_raw=synonyms_raw,
            model_name=str(getattr(settings, "SPARSE_SPLADE_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "SPARSE_SPLADE_DEVICE", "cpu") or "cpu"),
            batch_size=int(getattr(settings, "SPARSE_SPLADE_BATCH_SIZE", 8) or 8),
            max_length=int(getattr(settings, "SPARSE_SPLADE_MAX_LENGTH", 256) or 256),
            top_k=int(getattr(settings, "SPARSE_SPLADE_TOP_K", 128) or 128),
            min_weight=float(getattr(settings, "SPARSE_SPLADE_MIN_WEIGHT", 0.0) or 0.0),
        )
        encoder = get_sparse_encoder(
            provider=provider,
            synonyms=synonyms,
            synonyms_raw=synonyms_raw,
            model_name=str(getattr(settings, "SPARSE_SPLADE_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "SPARSE_SPLADE_DEVICE", "cpu") or "cpu"),
            batch_size=int(getattr(settings, "SPARSE_SPLADE_BATCH_SIZE", 8) or 8),
            max_length=int(getattr(settings, "SPARSE_SPLADE_MAX_LENGTH", 256) or 256),
            top_k=int(getattr(settings, "SPARSE_SPLADE_TOP_K", 128) or 128),
            min_weight=float(getattr(settings, "SPARSE_SPLADE_MIN_WEIGHT", 0.0) or 0.0),
        )
        return provider_config, encoder

    @staticmethod
    def _coerce_sparse_vector(value: Any) -> SparseVector:
        if isinstance(value, SparseVector):
            return value
        if not isinstance(value, dict):
            return SparseVector(weights={})

        weights: dict[str, float] = {}
        for key, weight in value.items():
            if key is None or weight is None:
                continue
            try:
                weights[str(key)] = float(weight)
            except (TypeError, ValueError, AttributeError):
                continue
        return SparseVector(weights=weights)

    @classmethod
    def _build_sparse_vectors_from_docs(cls, *, encoder: Any, docs: list[Document]) -> dict[str, SparseVector]:
        doc_ids: list[str] = []
        texts: list[str] = []
        for doc in docs or []:
            if doc is None or doc.id is None:
                continue
            doc_ids.append(str(doc.id))
            texts.append(str(doc.page_content or ""))

        vectors = encoder.encode_batch(texts)
        out: dict[str, SparseVector] = {}
        for idx, doc_id in enumerate(doc_ids):
            vector = vectors[idx] if idx < len(vectors) else SparseVector(weights={})
            out[doc_id] = cls._coerce_sparse_vector(vector)
        return out

    def _save_sparse_vectors(
        self,
        *,
        store_cls: Any,
        cache_key: str,
        provider_config: dict[str, Any],
        corpus_docs: list[Document],
        vectors: dict[str, SparseVector],
        version_token: str | None,
        context: str,
    ) -> str | None:
        if not bool(getattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", True)):
            return None

        try:
            store = store_cls(
                base_dir=str(getattr(settings, "SPARSE_RETRIEVAL_INDEX_DIR", SPARSE_INDEX_DIR_FALLBACK) or "")
            )
            store.save(
                cache_key=cache_key,
                provider_config=provider_config,
                corpus_fingerprint=self._sparse_corpus_fingerprint(corpus_docs),
                vectors=vectors,
                version_token=str(version_token or "").strip(),
            )
            return "ok"
        except Exception as exc:
            _log_retriever_fallback(context, exc)
            return "error"

    def _load_sparse_vectors(
        self,
        *,
        store_cls: Any,
        cache_key: str,
        provider_config: dict[str, Any],
        corpus_docs: list[Document],
        version_token: str | None,
        context: str,
    ) -> tuple[dict[str, SparseVector], str]:
        if not bool(getattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", True)):
            return {}, "skipped"

        try:
            store = store_cls(
                base_dir=str(getattr(settings, "SPARSE_RETRIEVAL_INDEX_DIR", SPARSE_INDEX_DIR_FALLBACK) or "")
            )
            loaded = store.load(
                cache_key=cache_key,
                provider_config=provider_config,
                expected_fingerprint=self._sparse_corpus_fingerprint(corpus_docs),
                expected_version_token=str(version_token or "").strip(),
            )
            if loaded:
                return loaded, "hit"
            return {}, "miss"
        except Exception as exc:
            _log_retriever_fallback(context, exc)
            return {}, "error"

    @staticmethod
    def _should_rebuild_sparse_index(
        *,
        sparse_vecs: dict[str, SparseVector],
        corpus_docs: list[Document],
        upsert_docs: list[Document],
    ) -> bool:
        return not sparse_vecs and bool(corpus_docs) and len(corpus_docs) > len(upsert_docs)

    @staticmethod
    def _collect_sparse_upsert_payload(upsert_docs: list[Document]) -> tuple[list[str], list[str]]:
        doc_ids: list[str] = []
        texts: list[str] = []
        for doc in upsert_docs:
            if doc is None or doc.id is None:
                continue
            doc_id = str(doc.id).strip()
            if not doc_id:
                continue
            doc_ids.append(doc_id)
            texts.append(str(doc.page_content or ""))
        return doc_ids, texts

    @classmethod
    def _apply_sparse_upsert_vectors(
        cls,
        *,
        sparse_vecs: dict[str, SparseVector],
        doc_ids: list[str],
        vectors: Any,
    ) -> None:
        for doc_id, vector in zip(doc_ids, vectors, strict=False):
            sparse_vecs[doc_id] = cls._coerce_sparse_vector(vector)

    def _build_sparse_index(
        self,
        *,
        cache_key: str,
        docs: list[Document],
        version_token: str | None = None,
    ) -> None:
        """
        Build (or rebuild) a sparse retrieval index for the current scope key.

        This is SPLADE-style sparse retrieval:
        - deterministic provider for tests/offline
        - optional SPLADE provider (HF/transformers) for production experiments (opt-in)

        Indices can be persisted to disk when enabled.
        """
        build_t0 = time.perf_counter()
        provider = self._sparse_provider_name()
        build_outcome = "ok"
        save_outcome: str | None = None
        from app.rag.retrieval.sparse_prometheus_metrics import (  # local import: optional dependency
            observe_sparse_index_build,
            observe_sparse_index_save,
        )

        try:
            from app.rag.retrieval.sparse import (
                SparseIndexStore,
                build_sparse_provider_config,
                get_sparse_encoder,
                parse_synonyms,
            )

            provider_config, encoder = self._resolve_sparse_runtime(
                provider=provider,
                build_sparse_provider_config=build_sparse_provider_config,
                get_sparse_encoder=get_sparse_encoder,
                parse_synonyms=parse_synonyms,
            )

            out = self._build_sparse_vectors_from_docs(encoder=encoder, docs=docs)
            self._sparse_doc_vectors[cache_key] = out
            save_outcome = self._save_sparse_vectors(
                store_cls=SparseIndexStore,
                cache_key=cache_key,
                provider_config=provider_config,
                corpus_docs=docs,
                vectors=out,
                version_token=version_token,
                context="_build_sparse_index",
            )
        except Exception as exc:
            _log_retriever_fallback("_build_sparse_index", exc)
            build_outcome = "error"
            raise
        finally:
            observe_sparse_index_build(
                provider=provider,
                kind="full",
                outcome=build_outcome,
                duration_sec=(time.perf_counter() - build_t0),
            )
            if save_outcome is not None:
                observe_sparse_index_save(provider=provider, outcome=save_outcome)

    def _upsert_sparse_index_incremental(
        self,
        *,
        cache_key: str,
        corpus_docs: list[Document],
        upsert_docs: list[Document],
        version_token: str | None = None,
    ) -> None:
        """
        Incrementally update the sparse index for a scope key.

        Rationale:
        - `_build_sparse_index` re-encodes the full corpus; that's fine for cold start but too expensive
          for frequent chunk-level upserts (document re-embed, patch, versioned re-index).
        - This helper updates/overwrites sparse vectors only for the provided `upsert_docs`, keeping the
          rest of the existing in-memory index intact.

        Safety:
        - If we don't have an existing index and the corpus is larger than the upsert batch, we fall
          back to a full rebuild to avoid a partial index that would cause false negatives.
        """
        if not upsert_docs:
            return

        build_t0 = time.perf_counter()
        build_outcome = "ok"
        load_outcome: str | None = None
        save_outcome: str | None = None

        provider = self._sparse_provider_name()

        from app.rag.retrieval.sparse_prometheus_metrics import (  # local import: optional dependency
            observe_sparse_index_build,
            observe_sparse_index_load,
            observe_sparse_index_save,
        )

        try:
            from app.rag.retrieval.sparse import (  # local import: keep optional deps isolated
                SparseIndexStore,
                build_sparse_provider_config,
                get_sparse_encoder,
                parse_synonyms,
            )

            provider_config, encoder = self._resolve_sparse_runtime(
                provider=provider,
                build_sparse_provider_config=build_sparse_provider_config,
                get_sparse_encoder=get_sparse_encoder,
                parse_synonyms=parse_synonyms,
            )

            sparse_vecs = self._sparse_doc_vectors.get(cache_key) or {}

            # Best-effort: load persisted index if we don't have an in-memory cache yet.
            if not sparse_vecs:
                sparse_vecs, load_outcome = self._load_sparse_vectors(
                    store_cls=SparseIndexStore,
                    cache_key=cache_key,
                    provider_config=provider_config,
                    corpus_docs=corpus_docs,
                    version_token=version_token,
                    context="_upsert_sparse_index_incremental",
                )

            # If the corpus is larger than the upsert batch and we don't have an existing index,
            # fall back to a full rebuild for correctness.
            if self._should_rebuild_sparse_index(
                sparse_vecs=sparse_vecs,
                corpus_docs=corpus_docs,
                upsert_docs=upsert_docs,
            ):
                build_outcome = "skipped"
                self._build_sparse_index(
                    cache_key=cache_key,
                    docs=corpus_docs,
                    version_token=str(version_token or "").strip(),
                )
                return

            doc_ids, texts = self._collect_sparse_upsert_payload(upsert_docs)
            if not doc_ids:
                build_outcome = "skipped"
                return

            self._apply_sparse_upsert_vectors(
                sparse_vecs=sparse_vecs,
                doc_ids=doc_ids,
                vectors=encoder.encode_batch(texts),
            )
            self._sparse_doc_vectors[cache_key] = sparse_vecs
            save_outcome = self._save_sparse_vectors(
                store_cls=SparseIndexStore,
                cache_key=cache_key,
                provider_config=provider_config,
                corpus_docs=corpus_docs,
                vectors=sparse_vecs,
                version_token=version_token,
                context="_upsert_sparse_index_incremental",
            )
        except Exception as exc:
            _log_retriever_fallback("_upsert_sparse_index_incremental", exc)
            build_outcome = "error"
            raise
        finally:
            observe_sparse_index_build(
                provider=provider,
                kind="incremental",
                outcome=build_outcome,
                duration_sec=(time.perf_counter() - build_t0),
            )
            if load_outcome is not None:
                observe_sparse_index_load(provider=provider, outcome=load_outcome)
            if save_outcome is not None:
                observe_sparse_index_save(provider=provider, outcome=save_outcome)

    def _sparse_corpus_fingerprint(self, docs: list[Document]) -> str:
        """
        Stable fingerprint for a sparse index corpus.

        Uses chunk_id + pipeline markers so persisted indices can be invalidated after re-chunking.
        """
        parts: list[str] = []
        for d in docs or []:
            if d is None or d.id is None:
                continue
            cid = str(d.id)
            meta = d.metadata or {}
            pk = meta.get("doc_pipeline_key") or meta.get("pipeline_hash") or ""
            parts.append(f"{cid}:{pk}")
        parts.sort()
        h = hashlib.sha256()
        for p in parts:
            h.update(p.encode("utf-8", errors="ignore"))
            h.update(b"\n")
        return h.hexdigest()[:24]

    def _sync_sparse_index_after_bm25_upsert(
        self,
        *,
        cache_key: str,
        tenant_id: UUID,
        dataset_scope_ids: tuple[UUID, ...],
        merged_docs: list[Document],
        upsert_docs: list[Document],
    ) -> None:
        if not self._effective_sparse_enabled():
            return

        try:
            with self._get_sparse_build_lock(cache_key):
                sparse_version_token = self._resolve_candidate_cache_corpus_token(
                    tenant_id=tenant_id,
                    document_ids=None,
                    dataset_ids=dataset_scope_ids,
                )
                self._upsert_sparse_index_incremental(
                    cache_key=cache_key,
                    corpus_docs=merged_docs,
                    upsert_docs=upsert_docs,
                    version_token=sparse_version_token,
                )
        except Exception as exc:
            logger.warning("Sparse index update failed for scope %s: %s", cache_key, str(exc)[:200])

    def _remove_sparse_vectors_for_deleted_chunks(self, *, scope_key: str, removed_ids: set[str]) -> None:
        if not removed_ids or not self._effective_sparse_enabled():
            return
        try:
            with self._get_sparse_build_lock(scope_key):
                vecs = self._sparse_doc_vectors.get(scope_key) or {}
                if not vecs:
                    return
                for cid in removed_ids:
                    vecs.pop(cid, None)
                self._sparse_doc_vectors[scope_key] = vecs
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    @staticmethod
    def _sparse_runtime_inputs(
        *,
        provider: str,
        build_sparse_provider_config: Any,
        parse_synonyms: Any,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        synonyms_raw = str(getattr(settings, "SPARSE_RETRIEVAL_SYNONYMS", "") or "")
        synonyms = parse_synonyms(synonyms_raw) if synonyms_raw.strip() else {}
        provider_config = build_sparse_provider_config(
            provider=provider,
            synonyms_raw=synonyms_raw,
            model_name=str(getattr(settings, "SPARSE_SPLADE_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "SPARSE_SPLADE_DEVICE", "cpu") or "cpu"),
            batch_size=int(getattr(settings, "SPARSE_SPLADE_BATCH_SIZE", 8) or 8),
            max_length=int(getattr(settings, "SPARSE_SPLADE_MAX_LENGTH", 256) or 256),
            top_k=int(getattr(settings, "SPARSE_SPLADE_TOP_K", 128) or 128),
            min_weight=float(getattr(settings, "SPARSE_SPLADE_MIN_WEIGHT", 0.0) or 0.0),
        )
        return synonyms_raw, synonyms, provider_config

    def _load_persisted_sparse_vectors_for_search(
        self,
        *,
        cache_key: str,
        provider: str,
        provider_config: dict[str, Any],
        docs: list[Document],
        version_token: str | None,
        store_cls: Any,
        observe_sparse_index_load: Any,
    ) -> tuple[dict[str, SparseVector], bool]:
        if not bool(getattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", True)):
            observe_sparse_index_load(provider=provider, outcome="skipped")
            return {}, False

        load_outcome = "miss"
        try:
            fp = self._sparse_corpus_fingerprint(docs)
            store = store_cls(
                base_dir=str(getattr(settings, "SPARSE_RETRIEVAL_INDEX_DIR", SPARSE_INDEX_DIR_FALLBACK) or "")
            )
            loaded = store.load(
                cache_key=cache_key,
                provider_config=provider_config,
                expected_fingerprint=fp,
                expected_version_token=str(version_token or "").strip(),
            )
            if loaded:
                self._sparse_doc_vectors[cache_key] = loaded
                load_outcome = "hit"
                return loaded, False
            return {}, False
        except Exception as exc:
            _log_retriever_fallback("_search_sparse", exc)
            load_outcome = "error"
            return {}, True
        finally:
            observe_sparse_index_load(provider=provider, outcome=load_outcome)

    def _ensure_sparse_vectors_for_search(
        self,
        *,
        cache_key: str,
        provider: str,
        provider_config: dict[str, Any],
        docs: list[Document],
        version_token: str | None,
        store_cls: Any,
        observe_sparse_index_load: Any,
    ) -> tuple[dict[str, SparseVector], bool, bool]:
        sparse_vecs = self._sparse_doc_vectors.get(cache_key) or {}
        had_load_error = False
        had_build_error = False
        if len(sparse_vecs) != len(docs):
            sparse_vecs, had_load_error = self._load_persisted_sparse_vectors_for_search(
                cache_key=cache_key,
                provider=provider,
                provider_config=provider_config,
                docs=docs,
                version_token=version_token,
                store_cls=store_cls,
                observe_sparse_index_load=observe_sparse_index_load,
            )

        if len(sparse_vecs) == len(docs):
            return sparse_vecs, had_load_error, had_build_error

        try:
            with self._get_sparse_build_lock(cache_key):
                sparse_vecs = self._sparse_doc_vectors.get(cache_key) or {}
                if len(sparse_vecs) != len(docs):
                    self._build_sparse_index(
                        cache_key=cache_key,
                        docs=docs,
                        version_token=version_token,
                    )
                    sparse_vecs = self._sparse_doc_vectors.get(cache_key) or {}
        except Exception as exc:
            _log_retriever_fallback("_search_sparse", exc)
            had_build_error = True
            sparse_vecs = self._sparse_doc_vectors.get(cache_key) or {}
        return sparse_vecs, had_load_error, had_build_error

    @staticmethod
    def _sparse_query_vector(encoder: Any, raw_query: str) -> SparseVector:
        q_raw = encoder.encode_batch([raw_query])[0]
        if isinstance(q_raw, SparseVector):
            return q_raw
        if isinstance(q_raw, dict):
            return SparseVector(weights={str(k): float(v) for k, v in q_raw.items() if k is not None and v is not None})
        return SparseVector(weights={})

    def _sparse_results_from_scores(
        self,
        *,
        scored: list[tuple[str, float]],
        docs: list[Document],
        document_ids: list[UUID] | None,
        metadata_filter: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        doc_by_id: dict[str, Document] = {str(d.id): d for d in docs if d is not None and d.id is not None}
        allowed_ids = {str(doc_id) for doc_id in document_ids} if document_ids else None
        results: list[dict[str, Any]] = []
        for doc_id, score in scored:
            doc = doc_by_id.get(str(doc_id))
            if doc is None:
                continue
            meta = doc.metadata or {}
            if not self._result_allowed_by_scope(
                metadata=meta,
                allowed_ids=allowed_ids,
                metadata_filter=metadata_filter,
                metadata_filter_enabled=self.metadata_filter_enabled,
                matcher=self._match_metadata_filter,
            ):
                continue
            out_meta = self._candidate_metadata_from_doc(meta, chunk_id=doc.id)
            out_meta["sparse_score"] = float(score)
            results.append(
                {
                    "chunk_id": doc.id,
                    "content": self._result_content_from_doc(doc),
                    "metadata": out_meta,
                    "score": float(score),
                }
            )
        return results

    def _record_sparse_search_status(
        self,
        *,
        provider_status: dict[str, Any],
        provider: str,
        outcome: str,
        reason: str,
        candidates_count: int,
        search_t0: float,
        observe_sparse_search: Any,
    ) -> None:
        try:
            self._last_sparse_provider_status = {
                **provider_status,
                "effective_provider": provider,
                "status": str(provider_status.get("status") or "ready"),
                "outcome": outcome,
                "reason": reason,
                "candidates": int(candidates_count or 0),
            }
        except (TypeError, ValueError, AttributeError):
            self._last_sparse_provider_status = {}
        observe_sparse_search(
            provider=provider,
            outcome=outcome,
            duration_sec=(time.perf_counter() - search_t0),
            candidates_count=candidates_count,
            reason=reason,
        )

    @staticmethod
    def _sparse_reason_after_index(
        *,
        reason: str,
        had_index_load_error: bool,
        had_index_build_error: bool,
        sparse_vecs: dict[str, SparseVector],
        docs: list[Document],
    ) -> str:
        if reason == "none" and had_index_load_error:
            return "index_load_error"
        if reason == "none" and had_index_build_error and len(sparse_vecs) != len(docs):
            return "index_build_failed"
        return reason

    @staticmethod
    def _empty_sparse_result(reason: str) -> tuple[list[dict[str, Any]], str, str, int]:
        if reason == "none":
            reason = "no_candidates"
        return [], "empty", reason, 0

    def _search_sparse_docs(
        self,
        *,
        raw_query: str,
        top_k: int,
        tenant_uuid: UUID,
        dataset_scope_ids: tuple[UUID, ...],
        cache_key: str,
        docs: list[Document],
        document_ids: list[UUID] | None,
        metadata_filter: dict[str, Any] | None,
        provider: str,
        reason: str,
        observe_sparse_index_load: Any,
    ) -> tuple[list[dict[str, Any]], str, str, int]:
        if not docs:
            return [], "skipped", "scope_empty", 0

        sparse_index_version_token = self._resolve_candidate_cache_corpus_token(
            tenant_id=tenant_uuid,
            document_ids=document_ids,
            dataset_ids=dataset_scope_ids,
        )

        from app.rag.retrieval.sparse import (
            SparseIndexStore,
            build_sparse_provider_config,
            get_sparse_encoder,
            parse_synonyms,
            topk_scores,
        )

        synonyms_raw, synonyms, provider_config = self._sparse_runtime_inputs(
            provider=provider,
            build_sparse_provider_config=build_sparse_provider_config,
            parse_synonyms=parse_synonyms,
        )
        sparse_vecs, had_index_load_error, had_index_build_error = self._ensure_sparse_vectors_for_search(
            cache_key=cache_key,
            provider=provider,
            provider_config=provider_config,
            docs=docs,
            version_token=sparse_index_version_token,
            store_cls=SparseIndexStore,
            observe_sparse_index_load=observe_sparse_index_load,
        )
        reason = self._sparse_reason_after_index(
            reason=reason,
            had_index_load_error=had_index_load_error,
            had_index_build_error=had_index_build_error,
            sparse_vecs=sparse_vecs,
            docs=docs,
        )

        encoder = get_sparse_encoder(
            provider=provider,
            synonyms=synonyms,
            synonyms_raw=synonyms_raw,
            model_name=str(getattr(settings, "SPARSE_SPLADE_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "SPARSE_SPLADE_DEVICE", "cpu") or "cpu"),
            batch_size=int(getattr(settings, "SPARSE_SPLADE_BATCH_SIZE", 8) or 8),
            max_length=int(getattr(settings, "SPARSE_SPLADE_MAX_LENGTH", 256) or 256),
            top_k=int(getattr(settings, "SPARSE_SPLADE_TOP_K", 128) or 128),
            min_weight=float(getattr(settings, "SPARSE_SPLADE_MIN_WEIGHT", 0.0) or 0.0),
        )
        scored = topk_scores(
            query_vec=self._sparse_query_vector(encoder, raw_query),
            docs=sparse_vecs,
            k=max(0, int(top_k or 0)),
        )
        if not scored:
            return self._empty_sparse_result(reason)

        results = self._sparse_results_from_scores(
            scored=scored,
            docs=docs,
            document_ids=document_ids,
            metadata_filter=metadata_filter,
        )
        if not results:
            return self._empty_sparse_result(reason)
        return self._top_scored_results(results, top_k), "ok", reason, len(results)

    def _search_sparse(
        self,
        query: str,
        top_k: int = 10,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Optional sparse retrieval channel (SPLADE-style scaffolding).

        - Uses the same BM25-scoped in-memory corpus as the sparse index source.
        - Uses a deterministic encoder by default (no model downloads).
        """
        raw_query = str(query or "").strip()
        if not raw_query:
            return []
        if not self._effective_sparse_enabled():
            return []

        tenant_uuid, dataset_scope_ids, cache_key, docs = self._bm25_scope_docs(
            tenant_id=tenant_id,
            document_ids=document_ids,
            metadata_filter=metadata_filter,
        )
        if tenant_uuid is None or cache_key is None:
            return []

        provider_status = self._resolve_sparse_provider_status(sparse_enabled=True)
        provider = str(provider_status.get("effective_provider") or "deterministic").strip().lower() or "deterministic"
        search_t0 = time.perf_counter()
        outcome = "error"
        candidates_count = 0
        reason = str(provider_status.get("reason") or "none")

        from app.rag.retrieval.sparse_prometheus_metrics import (  # local import: optional dependency
            observe_sparse_index_load,
            observe_sparse_search,
        )

        try:
            results, outcome, reason, candidates_count = self._search_sparse_docs(
                raw_query=raw_query,
                top_k=top_k,
                tenant_uuid=tenant_uuid,
                dataset_scope_ids=dataset_scope_ids,
                cache_key=cache_key,
                docs=docs,
                document_ids=document_ids,
                metadata_filter=metadata_filter,
                provider=provider,
                reason=reason,
                observe_sparse_index_load=observe_sparse_index_load,
            )
            return results
        except Exception as exc:
            _log_retriever_fallback("_search_sparse", exc)
            outcome = "error"
            if reason == "none":
                reason = "exception"
            raise
        finally:
            self._record_sparse_search_status(
                provider_status=provider_status,
                provider=provider,
                outcome=outcome,
                reason=reason,
                candidates_count=candidates_count,
                search_t0=search_t0,
                observe_sparse_search=observe_sparse_search,
            )
