"""ColBERT-style ANN index build/search for the hybrid retriever.

Split out of ``app.rag.retriever`` (see ``app.rag.retrieval.hybrid``). The
methods below run on the ``HybridRetriever`` instance via mixin inheritance.
"""

import hashlib
import threading
from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.retrieval.hybrid.common import (
    COLBERT_INDEX_DIR_FALLBACK,
    NON_CRITICAL_RETRIEVER_FALLBACK_LOG,
    _log_retriever_fallback,
    logger,
)


class ColbertIndexMixin:
    """ColBERT-style late-interaction ANN index: build, persist, incremental upsert, and search."""

    def _get_colbert_build_lock(self, cache_key: str) -> threading.Lock:
        return self._colbert_build_locks.setdefault(cache_key, threading.Lock())

    def _colbert_corpus_fingerprint(self, docs: list[Document]) -> str:
        """
        Stable fingerprint for a ColBERT ANN index corpus.

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

    @staticmethod
    def _resolve_colbert_max_docs() -> int:
        try:
            return max(0, int(getattr(settings, "COLBERT_RETRIEVAL_MAX_DOCS", 0) or 0))
        except (TypeError, ValueError, AttributeError):
            return 0

    def _colbert_scope_exceeds_limit(self, *, cache_key: str, docs: list[Document]) -> bool:
        max_docs = self._resolve_colbert_max_docs()
        if max_docs <= 0 or len(docs or []) <= max_docs:
            return False
        # Enforce a hard memory guard: don't build large matrices by accident.
        self._colbert_index_cache.pop(cache_key, None)
        return True

    @staticmethod
    def _colbert_provider_name() -> str:
        return str(getattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "deterministic") or "deterministic").strip().lower()

    @staticmethod
    def _build_colbert_provider_config(build_colbert_provider_config: Any, *, provider: str) -> dict[str, Any]:
        return build_colbert_provider_config(
            provider=provider,
            model_name=str(getattr(settings, "COLBERT_RETRIEVAL_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "COLBERT_RETRIEVAL_DEVICE", "cpu") or "cpu"),
            batch_size=int(getattr(settings, "COLBERT_RETRIEVAL_BATCH_SIZE", 16) or 16),
            max_length=int(getattr(settings, "COLBERT_RETRIEVAL_MAX_LENGTH", 256) or 256),
            deterministic_dim=int(getattr(settings, "COLBERT_RETRIEVAL_EMBED_DIM", 64) or 64),
        )

    @staticmethod
    def _collect_colbert_doc_text_pairs(docs: list[Document]) -> tuple[list[str], list[str]]:
        pairs: list[tuple[str, str]] = []
        for d in docs or []:
            if d is None or d.id is None:
                continue
            pairs.append((str(d.id), str(d.page_content or "")))

        pairs.sort(key=lambda x: x[0])
        return [p[0] for p in pairs], [p[1] for p in pairs]

    @staticmethod
    def _encode_colbert_texts(embedder: Any, texts: list[str]) -> Any:
        if texts:
            return embedder.encode_batch(texts)

        # Avoid numpy stack errors in deterministic embedder; empty corpora simply yield no hits.
        import numpy as np

        return np.zeros((0, 1), dtype=np.float32)

    @staticmethod
    def _persist_colbert_index(
        *,
        store_cls: Any,
        cache_key: str,
        provider_config: dict[str, Any],
        corpus_fingerprint: str,
        doc_ids: list[str],
        vectors: Any,
    ) -> None:
        if not bool(getattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", True)):
            return

        try:
            store = store_cls(
                base_dir=str(getattr(settings, "COLBERT_RETRIEVAL_INDEX_DIR", COLBERT_INDEX_DIR_FALLBACK) or "")
            )
            store.save(
                cache_key=cache_key,
                provider_config=provider_config,
                corpus_fingerprint=corpus_fingerprint,
                doc_ids=doc_ids,
                vectors=vectors,
            )
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _build_colbert_index(self, *, cache_key: str, docs: list[Document]) -> None:
        """
        Build (or rebuild) a ColBERT-style ANN index for the current scope key.

        Design:
        - Deterministic embedder for tests/offline (no model downloads)
        - Optional HF embedder (opt-in)
        - Persisted index to disk for fast cold-start in multi-process deployments
        """
        if self._colbert_scope_exceeds_limit(cache_key=cache_key, docs=docs):
            return

        from app.rag.retrieval.colbert_ann import (
            ColbertAnnIndex,
            ColbertAnnIndexStore,
            build_colbert_provider_config,
            get_dense_embedder,
        )

        provider = self._colbert_provider_name()
        provider_config = self._build_colbert_provider_config(build_colbert_provider_config, provider=provider)
        embedder = get_dense_embedder(
            provider=provider,
            model_name=str(getattr(settings, "COLBERT_RETRIEVAL_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "COLBERT_RETRIEVAL_DEVICE", "cpu") or "cpu"),
            batch_size=int(getattr(settings, "COLBERT_RETRIEVAL_BATCH_SIZE", 16) or 16),
            max_length=int(getattr(settings, "COLBERT_RETRIEVAL_MAX_LENGTH", 256) or 256),
            deterministic_dim=int(getattr(settings, "COLBERT_RETRIEVAL_EMBED_DIM", 64) or 64),
        )

        doc_ids, texts = self._collect_colbert_doc_text_pairs(docs)
        vecs = self._encode_colbert_texts(embedder, texts)
        fp = self._colbert_corpus_fingerprint(docs)
        index = ColbertAnnIndex(
            doc_ids=doc_ids,
            vectors=vecs,
            corpus_fingerprint=fp,
            provider_config=dict(provider_config),
        )
        self._colbert_index_cache[cache_key] = index

        self._persist_colbert_index(
            store_cls=ColbertAnnIndexStore,
            cache_key=cache_key,
            provider_config=provider_config,
            corpus_fingerprint=fp,
            doc_ids=doc_ids,
            vectors=vecs,
        )

    def _colbert_incremental_base_parts(
        self,
        *,
        cache_key: str,
        provider_config: dict[str, Any],
    ) -> tuple[list[Any], Any | None]:
        base = self._colbert_index_cache.get(cache_key)
        if base is None:
            return [], None
        base_cfg = dict(getattr(base, "provider_config", {}) or {})
        base_ids = list(getattr(base, "doc_ids", []) or [])
        base_vecs = getattr(base, "vectors", None)
        if not base_ids or base_vecs is None or base_cfg != dict(provider_config):
            return [], None
        return base_ids, base_vecs

    @staticmethod
    def _collect_colbert_upsert_payload(upsert_docs: list[Document]) -> tuple[list[str], list[str]]:
        up_ids: list[str] = []
        up_texts: list[str] = []
        for d in upsert_docs:
            if d is None or d.id is None:
                continue
            cid = str(d.id).strip()
            if not cid:
                continue
            up_ids.append(cid)
            up_texts.append(str(d.page_content or ""))
        return up_ids, up_texts

    def _colbert_incremental_vectors(
        self,
        *,
        cache_key: str,
        corpus_docs: list[Document],
        upsert_docs: list[Document],
        base_ids: list[Any],
        base_vecs: Any,
        embedder: Any,
    ) -> tuple[list[str], Any] | None:
        try:
            import numpy as np  # local import

            mat = np.asarray(base_vecs, dtype=np.float32)
            if mat.ndim != 2 or int(mat.shape[0]) != len(base_ids):
                return None

            vec_by_id: dict[str, np.ndarray] = {
                str(doc_id): mat[i] for i, doc_id in enumerate(base_ids) if doc_id is not None
            }
            up_ids, up_texts = self._collect_colbert_upsert_payload(upsert_docs)
            if not up_ids:
                return None

            corpus_ids = {str(d.id) for d in corpus_docs if d is not None and d.id is not None}
            missing = set(corpus_ids) - set(vec_by_id.keys())
            if missing and (missing - set(up_ids)):
                self._build_colbert_index(cache_key=cache_key, docs=corpus_docs)
                return None

            up_mat = np.asarray(embedder.encode_batch(up_texts), dtype=np.float32)
            if up_mat.ndim != 2 or int(up_mat.shape[0]) != len(up_ids):
                return None

            for cid, row in zip(up_ids, up_mat, strict=False):
                vec_by_id[str(cid)] = np.asarray(row, dtype=np.float32)

            doc_ids = sorted(vec_by_id.keys())
            vectors = np.stack([vec_by_id[cid] for cid in doc_ids], axis=0).astype(np.float32, copy=False)
            return doc_ids, vectors
        except Exception as exc:
            _log_retriever_fallback("_upsert_colbert_index_incremental", exc)
            return None

    def _upsert_colbert_index_incremental(
        self,
        *,
        cache_key: str,
        corpus_docs: list[Document],
        upsert_docs: list[Document],
    ) -> None:
        """
        Incrementally update a ColBERT ANN index for a scope key.

        This updates/overwrites vectors only for `upsert_docs` when an index already exists,
        avoiding a full re-embed of the corpus on each chunk-level upsert.
        """
        if not upsert_docs or not corpus_docs:
            return

        if self._colbert_scope_exceeds_limit(cache_key=cache_key, docs=corpus_docs):
            return

        from app.rag.retrieval.colbert_ann import (  # local import: optional deps
            ColbertAnnIndex,
            ColbertAnnIndexStore,
            build_colbert_provider_config,
            get_dense_embedder,
        )

        provider = self._colbert_provider_name()
        provider_config = self._build_colbert_provider_config(build_colbert_provider_config, provider=provider)
        base_ids, base_vecs = self._colbert_incremental_base_parts(
            cache_key=cache_key,
            provider_config=provider_config,
        )
        if not base_ids or base_vecs is None:
            # No compatible index in memory: keep lazy-build semantics for cold start.
            return

        embedder = get_dense_embedder(
            provider=provider,
            model_name=str(getattr(settings, "COLBERT_RETRIEVAL_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "COLBERT_RETRIEVAL_DEVICE", "cpu") or "cpu"),
            batch_size=int(getattr(settings, "COLBERT_RETRIEVAL_BATCH_SIZE", 16) or 16),
            max_length=int(getattr(settings, "COLBERT_RETRIEVAL_MAX_LENGTH", 256) or 256),
            deterministic_dim=int(getattr(settings, "COLBERT_RETRIEVAL_EMBED_DIM", 64) or 64),
        )
        packed = self._colbert_incremental_vectors(
            cache_key=cache_key,
            corpus_docs=corpus_docs,
            upsert_docs=upsert_docs,
            base_ids=base_ids,
            base_vecs=base_vecs,
            embedder=embedder,
        )
        if packed is None:
            return
        doc_ids, vectors = packed

        expected_fp = self._colbert_corpus_fingerprint(corpus_docs)
        index = ColbertAnnIndex(
            doc_ids=doc_ids,
            vectors=vectors,
            corpus_fingerprint=expected_fp,
            provider_config=dict(provider_config),
        )
        self._colbert_index_cache[cache_key] = index

        self._persist_colbert_index(
            store_cls=ColbertAnnIndexStore,
            cache_key=cache_key,
            provider_config=provider_config,
            corpus_fingerprint=expected_fp,
            doc_ids=doc_ids,
            vectors=vectors,
        )

    def _sync_colbert_index_after_bm25_upsert(
        self,
        *,
        cache_key: str,
        merged_docs: list[Document],
        upsert_docs: list[Document],
    ) -> None:
        if not bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)):
            return

        try:
            with self._get_colbert_build_lock(cache_key):
                self._upsert_colbert_index_incremental(
                    cache_key=cache_key,
                    corpus_docs=merged_docs,
                    upsert_docs=upsert_docs,
                )
        except Exception as exc:
            logger.warning("ColBERT index update failed for scope %s: %s", cache_key, str(exc)[:200])

    def _remove_colbert_vectors_for_deleted_chunks(
        self,
        *,
        scope_key: str,
        removed_ids: set[str],
        filtered: list[Document],
    ) -> None:
        if not removed_ids or not bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)):
            return
        try:
            with self._get_colbert_build_lock(scope_key):
                idx = self._colbert_index_cache.get(scope_key)
                if idx is None:
                    return
                ids0 = list(getattr(idx, "doc_ids", []) or [])
                vecs0 = getattr(idx, "vectors", None)
                if not ids0 or vecs0 is None:
                    return
                self._replace_colbert_index_without_deleted_chunks(
                    scope_key=scope_key,
                    idx=idx,
                    ids0=ids0,
                    vecs0=vecs0,
                    removed_ids=removed_ids,
                    filtered=filtered,
                )
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _replace_colbert_index_without_deleted_chunks(
        self,
        *,
        scope_key: str,
        idx: Any,
        ids0: list[Any],
        vecs0: Any,
        removed_ids: set[str],
        filtered: list[Document],
    ) -> None:
        try:
            import numpy as np

            mat = np.asarray(vecs0, dtype=np.float32)
            keep: list[int] = [i for i, cid in enumerate(ids0) if str(cid) not in removed_ids]
            if not keep:
                self._colbert_index_cache.pop(scope_key, None)
                return
            new_ids = [str(ids0[i]) for i in keep]
            new_mat = mat[keep, :]
            fp = self._colbert_corpus_fingerprint(filtered)
            from app.rag.retrieval.colbert_ann import ColbertAnnIndex  # noqa: WPS433

            self._colbert_index_cache[scope_key] = ColbertAnnIndex(
                doc_ids=new_ids,
                vectors=new_mat,
                corpus_fingerprint=fp,
                provider_config=dict(getattr(idx, "provider_config", {}) or {}),
            )
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _resolve_colbert_readiness(
        self, resolve_provider_capability: Any, *, docs: list[Document]
    ) -> tuple[int, dict[str, Any]]:
        max_docs = self._resolve_colbert_max_docs()
        readiness = resolve_provider_capability(
            colbert_enabled=bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)),
            requested_provider=self._colbert_provider_name(),
            model_name=str(getattr(settings, "COLBERT_RETRIEVAL_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "COLBERT_RETRIEVAL_DEVICE", "cpu") or "cpu"),
            docs_count=int(len(docs or [])),
            max_docs=int(max_docs),
        )
        self._update_channel_metric("colbert_ann", {"readiness": dict(readiness or {})})
        return max_docs, dict(readiness or {})

    def _mark_colbert_skipped(
        self,
        *,
        reason: str,
        cache_key: str | None = None,
        docs_count: int | None = None,
        max_docs: int | None = None,
    ) -> None:
        values: dict[str, Any] = {"skipped_reason": reason}
        if docs_count is not None:
            values["docs_n"] = int(docs_count)
        if max_docs is not None:
            values["max_docs"] = int(max_docs)
        self._update_channel_metric("colbert_ann", values)
        if reason == "too_many_docs" and cache_key:
            try:
                self._colbert_index_cache.pop(cache_key, None)
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    @staticmethod
    def _colbert_index_matches(index: Any, *, expected_fp: str, provider_config: dict[str, Any]) -> bool:
        try:
            return (
                index is not None
                and str(getattr(index, "corpus_fingerprint", "") or "") == str(expected_fp or "")
                and dict(getattr(index, "provider_config", {}) or {}) == dict(provider_config)
            )
        except (TypeError, ValueError, AttributeError):
            return False

    def _load_colbert_index_from_store(
        self,
        *,
        store_cls: Any,
        cache_key: str,
        provider_config: dict[str, Any],
        expected_fp: str,
    ) -> Any | None:
        if not bool(getattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", True)):
            return None
        try:
            store = store_cls(
                base_dir=str(getattr(settings, "COLBERT_RETRIEVAL_INDEX_DIR", COLBERT_INDEX_DIR_FALLBACK) or "")
            )
            loaded = store.load(cache_key=cache_key, provider_config=provider_config, expected_fingerprint=expected_fp)
            if loaded is not None:
                self._colbert_index_cache[cache_key] = loaded
            return loaded
        except Exception as exc:
            _log_retriever_fallback("_search_colbert_ann", exc)
            return None

    def _ensure_colbert_search_index(
        self,
        *,
        cache_key: str,
        docs: list[Document],
        provider_config: dict[str, Any],
        expected_fp: str,
        store_cls: Any,
    ) -> Any | None:
        index = self._colbert_index_cache.get(cache_key)
        if self._colbert_index_matches(index, expected_fp=expected_fp, provider_config=provider_config):
            return index

        loaded = self._load_colbert_index_from_store(
            store_cls=store_cls,
            cache_key=cache_key,
            provider_config=provider_config,
            expected_fp=expected_fp,
        )
        if self._colbert_index_matches(loaded, expected_fp=expected_fp, provider_config=provider_config):
            return loaded

        try:
            with self._get_colbert_build_lock(cache_key):
                index = self._colbert_index_cache.get(cache_key)
                if self._colbert_index_matches(index, expected_fp=expected_fp, provider_config=provider_config):
                    return index
                self._build_colbert_index(cache_key=cache_key, docs=docs)
                index = self._colbert_index_cache.get(cache_key)
                if self._colbert_index_matches(index, expected_fp=expected_fp, provider_config=provider_config):
                    return index
        except Exception as exc:
            _log_retriever_fallback("_search_colbert_ann", exc)
        return None

    @staticmethod
    def _colbert_query_vector(get_dense_embedder: Any, *, provider: str, raw_query: str) -> Any | None:
        embedder = get_dense_embedder(
            provider=provider,
            model_name=str(getattr(settings, "COLBERT_RETRIEVAL_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "COLBERT_RETRIEVAL_DEVICE", "cpu") or "cpu"),
            batch_size=int(getattr(settings, "COLBERT_RETRIEVAL_BATCH_SIZE", 16) or 16),
            max_length=int(getattr(settings, "COLBERT_RETRIEVAL_MAX_LENGTH", 256) or 256),
            deterministic_dim=int(getattr(settings, "COLBERT_RETRIEVAL_EMBED_DIM", 64) or 64),
        )
        q_mat = embedder.encode_batch([raw_query])
        try:
            return q_mat[0]
        except (TypeError, ValueError, AttributeError):
            return None

    def _colbert_results_from_scores(
        self,
        *,
        scored: list[tuple[int, float]],
        doc_ids: list[Any],
        docs: list[Document],
        document_ids: list[UUID] | None,
        metadata_filter: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        doc_by_id: dict[str, Document] = {str(d.id): d for d in docs if d is not None and d.id is not None}
        allowed_ids = {str(doc_id) for doc_id in document_ids} if document_ids else None
        results: list[dict[str, Any]] = []
        for idx, score in scored:
            if idx < 0 or idx >= len(doc_ids):
                continue
            doc_id = str(doc_ids[int(idx)])
            doc = doc_by_id.get(doc_id)
            if doc is None:
                continue
            meta = dict(doc.metadata or {})
            if not self._result_allowed_by_scope(
                metadata=meta,
                allowed_ids=allowed_ids,
                metadata_filter=metadata_filter,
                metadata_filter_enabled=self.metadata_filter_enabled,
                matcher=self._match_metadata_filter,
            ):
                continue
            meta.setdefault("chunk_id", doc_id)
            meta["colbert_score"] = float(score)
            results.append(
                {
                    "chunk_id": doc_id,
                    "content": self._result_content_from_doc(doc),
                    "metadata": meta,
                    "score": float(score),
                }
            )
        return results

    def _search_colbert_ann_docs(
        self,
        *,
        raw_query: str,
        top_k: int,
        cache_key: str,
        docs: list[Document],
        document_ids: list[UUID] | None,
        metadata_filter: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        from app.rag.retrieval.colbert_ann import (
            ColbertAnnIndexStore,
            build_colbert_provider_config,
            get_dense_embedder,
            resolve_colbert_ann_provider_capability,
            topk_cosine_scores,
        )

        max_docs, readiness = self._resolve_colbert_readiness(resolve_colbert_ann_provider_capability, docs=docs)
        if str(readiness.get("reason") or "") == "too_many_docs":
            self._mark_colbert_skipped(
                reason="too_many_docs",
                cache_key=cache_key,
                docs_count=len(docs or []),
                max_docs=max_docs,
            )
            return []

        provider = str(readiness.get("effective_provider") or "deterministic").strip().lower() or "deterministic"
        if not bool(readiness.get("ready", False)):
            self._mark_colbert_skipped(reason="provider_unready")
            return []

        provider_config = self._build_colbert_provider_config(build_colbert_provider_config, provider=provider)
        index = self._ensure_colbert_search_index(
            cache_key=cache_key,
            docs=docs,
            provider_config=provider_config,
            expected_fp=self._colbert_corpus_fingerprint(docs),
            store_cls=ColbertAnnIndexStore,
        )
        if index is None:
            return []

        q_vec = self._colbert_query_vector(get_dense_embedder, provider=provider, raw_query=raw_query)
        if q_vec is None:
            return []

        doc_vecs = getattr(index, "vectors", None)
        doc_ids = list(getattr(index, "doc_ids", []) or [])
        if doc_vecs is None or not doc_ids:
            return []

        scored = topk_cosine_scores(query_vec=q_vec, doc_vecs=doc_vecs, k=max(0, int(top_k or 0)))
        if not scored:
            return []

        return self._colbert_results_from_scores(
            scored=scored,
            doc_ids=doc_ids,
            docs=docs,
            document_ids=document_ids,
            metadata_filter=metadata_filter,
        )

    def _search_colbert_ann(
        self,
        query: str,
        top_k: int = 10,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Optional ColBERT-style ANN retrieval channel (production scaffold).

        Notes:
        - Uses the same BM25-scoped in-memory corpus as the index source.
        - Deterministic by default (no model downloads), with optional HF provider.
        - Persists index artifacts to disk when enabled (best-effort).
        """
        raw_query = str(query or "").strip()
        if not raw_query:
            return []
        if not bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)):
            return []

        _tenant_uuid, _dataset_scope_ids, cache_key, docs = self._bm25_scope_docs(
            tenant_id=tenant_id,
            document_ids=document_ids,
            metadata_filter=metadata_filter,
        )
        if cache_key is None:
            return []
        if not docs:
            return []
        return self._search_colbert_ann_docs(
            raw_query=raw_query,
            top_k=top_k,
            cache_key=cache_key,
            docs=docs,
            document_ids=document_ids,
            metadata_filter=metadata_filter,
        )
