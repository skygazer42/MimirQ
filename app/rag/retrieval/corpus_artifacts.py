"""Owned sparse and ColBERT corpus artifacts shared by index writers and query readers."""

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.retrieval.hybrid.common import (
    NON_CRITICAL_RETRIEVER_FALLBACK_LOG,
    _log_retriever_fallback,
    logger,
)
from app.rag.retrieval.sparse import SparseVector

if TYPE_CHECKING:
    from app.rag.retrieval.colbert_ann import ColbertAnnIndex


def corpus_document_fingerprint(docs: list[Document]) -> str:
    rows = [
        (
            str(document.id),
            str(document.metadata.get("doc_pipeline_key") or document.metadata.get("pipeline_hash") or ""),
            hashlib.sha256(document.page_content.encode("utf-8", errors="ignore")).hexdigest(),
        )
        for document in docs
        if document.id is not None
    ]
    payload = json.dumps(sorted(rows), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


class CorpusBuildLock:
    """A reentrant build lock whose users remain visible to scope eviction."""

    def __init__(self) -> None:
        self._gate = threading.RLock()
        self._state = threading.Lock()
        self._users = 0

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        with self._state:
            self._users += 1
        try:
            acquired = self._gate.acquire(blocking, timeout)
        except BaseException:
            with self._state:
                self._users -= 1
            raise
        if not acquired:
            with self._state:
                self._users -= 1
        return acquired

    def release(self) -> None:
        self._gate.release()
        with self._state:
            self._users -= 1

    def locked(self) -> bool:
        with self._state:
            return self._users > 0

    def __enter__(self) -> "CorpusBuildLock":
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class SparseCorpusIndex:
    def __init__(self) -> None:
        self._sparse_doc_vectors: dict[str, dict[str, SparseVector]] = {}
        self._sparse_build_locks: dict[str, CorpusBuildLock] = {}
        self._sparse_provider_configs: dict[str, dict[str, Any]] = {}
        self._sparse_corpus_fingerprints: dict[str, str] = {}

    def _get_sparse_build_lock(self, cache_key: str) -> CorpusBuildLock:
        return self._sparse_build_locks.setdefault(cache_key, CorpusBuildLock())

    @staticmethod
    def _resolve_sparse_runtime(
        *, provider: str, build_sparse_provider_config: Any, get_sparse_encoder: Any, parse_synonyms: Any
    ) -> tuple[dict[str, Any], Any]:
        synonyms_raw = settings.SPARSE_RETRIEVAL_SYNONYMS
        synonyms = parse_synonyms(synonyms_raw) if synonyms_raw.strip() else {}
        provider_config = build_sparse_provider_config(provider=provider, synonyms_raw=synonyms_raw)
        encoder = get_sparse_encoder(provider=provider, synonyms=synonyms, synonyms_raw=synonyms_raw)
        return (provider_config, encoder)

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
        if not settings.SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED:
            return None
        try:
            store = store_cls(base_dir=str(settings.SPARSE_RETRIEVAL_INDEX_DIR or ""))
            store.save(
                cache_key=cache_key,
                provider_config=provider_config,
                corpus_fingerprint=self._sparse_corpus_fingerprint(corpus_docs),
                vectors=vectors,
                version_token=str((version_token if version_token is not None else "")).strip(),
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
        if not settings.SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED:
            return ({}, "skipped")
        try:
            store = store_cls(base_dir=str(settings.SPARSE_RETRIEVAL_INDEX_DIR or ""))
            loaded = store.load(
                cache_key=cache_key,
                provider_config=provider_config,
                expected_fingerprint=self._sparse_corpus_fingerprint(corpus_docs),
                expected_version_token=str((version_token if version_token is not None else "")).strip(),
            )
            if loaded:
                return (loaded, "hit")
            return ({}, "miss")
        except Exception as exc:
            _log_retriever_fallback(context, exc)
            return ({}, "error")

    @staticmethod
    def _should_rebuild_sparse_index(
        *, sparse_vecs: dict[str, SparseVector], corpus_docs: list[Document], upsert_docs: list[Document]
    ) -> bool:
        return not sparse_vecs and bool(corpus_docs) and (len(corpus_docs) > len(upsert_docs))

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
        return (doc_ids, texts)

    @classmethod
    def _apply_sparse_upsert_vectors(
        cls, *, sparse_vecs: dict[str, SparseVector], doc_ids: list[str], vectors: Any
    ) -> None:
        for doc_id, vector in zip(doc_ids, vectors, strict=False):
            sparse_vecs[doc_id] = cls._coerce_sparse_vector(vector)

    def _build_sparse_index(
        self, *, cache_key: str, docs: list[Document], version_token: str | None = None, provider: str
    ) -> None:
        """
        Build (or rebuild) a sparse retrieval index for the current scope key.

        Only the deterministic provider for tests/offline is supported.
        The in-process SPLADE model provider has been retired.

        Indices can be persisted to disk when enabled.
        """
        with self._get_sparse_build_lock(cache_key):
            build_t0 = time.perf_counter()
            build_outcome = "ok"
            save_outcome: str | None = None
            from app.rag.retrieval.sparse_prometheus_metrics import (
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
                self._sparse_corpus_fingerprints[cache_key] = self._sparse_corpus_fingerprint(docs)
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
                    provider=provider, kind="full", outcome=build_outcome, duration_sec=time.perf_counter() - build_t0
                )
                if save_outcome is not None:
                    observe_sparse_index_save(provider=provider, outcome=save_outcome)
            self._sparse_provider_configs[cache_key] = dict(provider_config)

    def _upsert_sparse_index_incremental(
        self,
        *,
        cache_key: str,
        corpus_docs: list[Document],
        upsert_docs: list[Document],
        version_token: str | None = None,
        provider: str,
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
        with self._get_sparse_build_lock(cache_key):
            if not upsert_docs:
                return
            build_t0 = time.perf_counter()
            build_outcome = "ok"
            load_outcome: str | None = None
            save_outcome: str | None = None
            from app.rag.retrieval.sparse_prometheus_metrics import (
                observe_sparse_index_build,
                observe_sparse_index_load,
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
                if self._sparse_provider_configs.get(cache_key) != provider_config:
                    self._sparse_doc_vectors.pop(cache_key, None)
                sparse_vecs = dict(self._sparse_doc_vectors.get(cache_key, {}))
                if not sparse_vecs:
                    sparse_vecs, load_outcome = self._load_sparse_vectors(
                        store_cls=SparseIndexStore,
                        cache_key=cache_key,
                        provider_config=provider_config,
                        corpus_docs=corpus_docs,
                        version_token=version_token,
                        context="_upsert_sparse_index_incremental",
                    )
                if self._should_rebuild_sparse_index(
                    sparse_vecs=sparse_vecs, corpus_docs=corpus_docs, upsert_docs=upsert_docs
                ):
                    build_outcome = "skipped"
                    self._build_sparse_index(
                        cache_key=cache_key,
                        docs=corpus_docs,
                        version_token=str((version_token if version_token is not None else "")).strip(),
                        provider=provider,
                    )
                    return
                doc_ids, texts = self._collect_sparse_upsert_payload(upsert_docs)
                if not doc_ids:
                    build_outcome = "skipped"
                    return
                self._apply_sparse_upsert_vectors(
                    sparse_vecs=sparse_vecs, doc_ids=doc_ids, vectors=encoder.encode_batch(texts)
                )
                self._sparse_doc_vectors[cache_key] = sparse_vecs
                self._sparse_corpus_fingerprints[cache_key] = self._sparse_corpus_fingerprint(corpus_docs)
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
                    duration_sec=time.perf_counter() - build_t0,
                )
                if load_outcome is not None:
                    observe_sparse_index_load(provider=provider, outcome=load_outcome)
                if save_outcome is not None:
                    observe_sparse_index_save(provider=provider, outcome=save_outcome)
            self._sparse_provider_configs[cache_key] = dict(provider_config)

    def _sparse_corpus_fingerprint(self, docs: list[Document]) -> str:
        return corpus_document_fingerprint(docs)

    def _remove_sparse_vectors_for_deleted_chunks(
        self, *, scope_key: str, removed_ids: set[str], filtered: list[Document]
    ) -> None:
        if not removed_ids:
            return
        try:
            with self._get_sparse_build_lock(scope_key):
                vecs = dict(self._sparse_doc_vectors.get(scope_key, {}))
                if not vecs:
                    return
                for cid in removed_ids:
                    vecs.pop(cid, None)
                self._sparse_doc_vectors[scope_key] = vecs
                self._sparse_corpus_fingerprints[scope_key] = self._sparse_corpus_fingerprint(filtered)
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    @staticmethod
    def _sparse_runtime_inputs(
        *, provider: str, build_sparse_provider_config: Any, parse_synonyms: Any
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        synonyms_raw = settings.SPARSE_RETRIEVAL_SYNONYMS
        synonyms = parse_synonyms(synonyms_raw) if synonyms_raw.strip() else {}
        provider_config = build_sparse_provider_config(provider=provider, synonyms_raw=synonyms_raw)
        return (synonyms_raw, synonyms, provider_config)

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
        if not settings.SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED:
            observe_sparse_index_load(provider=provider, outcome="skipped")
            return ({}, False)
        load_outcome = "miss"
        try:
            fp = self._sparse_corpus_fingerprint(docs)
            store = store_cls(base_dir=str(settings.SPARSE_RETRIEVAL_INDEX_DIR or ""))
            loaded = store.load(
                cache_key=cache_key,
                provider_config=provider_config,
                expected_fingerprint=fp,
                expected_version_token=str((version_token if version_token is not None else "")).strip(),
            )
            if loaded:
                self._sparse_doc_vectors[cache_key] = loaded
                self._sparse_provider_configs[cache_key] = dict(provider_config)
                self._sparse_corpus_fingerprints[cache_key] = fp
                load_outcome = "hit"
                return (loaded, False)
            return ({}, False)
        except Exception as exc:
            _log_retriever_fallback("_search_sparse", exc)
            load_outcome = "error"
            return ({}, True)
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
    ) -> tuple[dict[str, SparseVector], bool, Exception | None]:
        with self._get_sparse_build_lock(cache_key):
            fingerprint = self._sparse_corpus_fingerprint(docs)
            if (
                self._sparse_provider_configs.get(cache_key) != provider_config
                or self._sparse_corpus_fingerprints.get(cache_key) != fingerprint
            ):
                self._sparse_doc_vectors.pop(cache_key, None)
            sparse_vecs = self._sparse_doc_vectors.get(cache_key) or {}
            had_load_error = False
            build_error: Exception | None = None
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
                return (sparse_vecs, had_load_error, build_error)
            try:
                self._build_sparse_index(cache_key=cache_key, docs=docs, version_token=version_token, provider=provider)
                sparse_vecs = self._sparse_doc_vectors.get(cache_key) or {}
            except Exception as exc:
                _log_retriever_fallback("_search_sparse", exc)
                build_error = exc
                sparse_vecs = self._sparse_doc_vectors.get(cache_key) or {}
            return (sparse_vecs, had_load_error, build_error)

    def clear_scope(self, cache_key: str) -> None:
        with self._get_sparse_build_lock(cache_key):
            self._sparse_doc_vectors.pop(cache_key, None)
            self._sparse_provider_configs.pop(cache_key, None)
            self._sparse_corpus_fingerprints.pop(cache_key, None)

    def clear(self) -> None:
        self._sparse_doc_vectors.clear()
        self._sparse_provider_configs.clear()
        self._sparse_corpus_fingerprints.clear()
        self._sparse_build_locks.clear()


class ColbertCorpusIndex:
    def __init__(self) -> None:
        self._colbert_index_cache: dict[str, ColbertAnnIndex] = {}
        self._colbert_build_locks: dict[str, CorpusBuildLock] = {}

    def _get_colbert_build_lock(self, cache_key: str) -> CorpusBuildLock:
        return self._colbert_build_locks.setdefault(cache_key, CorpusBuildLock())

    def _colbert_corpus_fingerprint(self, docs: list[Document]) -> str:
        return corpus_document_fingerprint(docs)

    @staticmethod
    def _resolve_colbert_max_docs() -> int:
        return max(0, settings.COLBERT_RETRIEVAL_MAX_DOCS)

    def _colbert_scope_exceeds_limit(self, *, cache_key: str, docs: list[Document]) -> bool:
        max_docs = self._resolve_colbert_max_docs()
        if max_docs <= 0 or len(docs or []) <= max_docs:
            return False
        self._colbert_index_cache.pop(cache_key, None)
        return True

    @staticmethod
    def _colbert_provider_name() -> str:
        return (settings.COLBERT_RETRIEVAL_PROVIDER or "deterministic").strip().lower()

    @staticmethod
    def _build_colbert_provider_config(build_colbert_provider_config: Any, *, provider: str) -> dict[str, Any]:
        return build_colbert_provider_config(
            provider=provider, deterministic_dim=settings.COLBERT_RETRIEVAL_EMBED_DIM or 64
        )

    @staticmethod
    def _collect_colbert_doc_text_pairs(docs: list[Document]) -> tuple[list[str], list[str]]:
        pairs: list[tuple[str, str]] = []
        for d in docs or []:
            if d is None or d.id is None:
                continue
            pairs.append((str(d.id), str(d.page_content or "")))
        pairs.sort(key=lambda x: x[0])
        return ([p[0] for p in pairs], [p[1] for p in pairs])

    @staticmethod
    def _encode_colbert_texts(embedder: Any, texts: list[str]) -> Any:
        if texts:
            return embedder.encode_batch(texts)
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
        if not settings.COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED:
            return
        try:
            store = store_cls(base_dir=str(settings.COLBERT_RETRIEVAL_INDEX_DIR or ""))
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
        Build (or rebuild) a deterministic dense index for the current scope key.

        Design:
        - Deterministic embedder for tests/offline (no model downloads)
        - Exact cosine scoring over the resulting dense vectors
        - Optional persistence using the existing index format
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
        embedder = get_dense_embedder(provider=provider, deterministic_dim=settings.COLBERT_RETRIEVAL_EMBED_DIM or 64)
        doc_ids, texts = self._collect_colbert_doc_text_pairs(docs)
        vecs = self._encode_colbert_texts(embedder, texts)
        fp = self._colbert_corpus_fingerprint(docs)
        index = ColbertAnnIndex(
            doc_ids=doc_ids, vectors=vecs, corpus_fingerprint=fp, provider_config=dict(provider_config)
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
        self, *, cache_key: str, provider_config: dict[str, Any]
    ) -> tuple[list[str], Any | None]:
        base = self._colbert_index_cache.get(cache_key)
        if base is None:
            return ([], None)
        base_cfg = dict(base.provider_config or {})
        base_ids = list(base.doc_ids or [])
        base_vecs = base.vectors
        if not base_ids or base_vecs is None or base_cfg != dict(provider_config):
            return ([], None)
        return (base_ids, base_vecs)

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
        return (up_ids, up_texts)

    def _colbert_incremental_vectors(
        self,
        *,
        cache_key: str,
        corpus_docs: list[Document],
        upsert_docs: list[Document],
        base_ids: list[str],
        base_vecs: Any,
        embedder: Any,
    ) -> tuple[list[str], Any] | None:
        try:
            import numpy as np

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
            if missing and missing - set(up_ids):
                self._build_colbert_index(cache_key=cache_key, docs=corpus_docs)
                return None
            up_mat = np.asarray(embedder.encode_batch(up_texts), dtype=np.float32)
            if up_mat.ndim != 2 or int(up_mat.shape[0]) != len(up_ids):
                return None
            for cid, row in zip(up_ids, up_mat, strict=False):
                vec_by_id[str(cid)] = np.asarray(row, dtype=np.float32)
            doc_ids = sorted(vec_by_id.keys())
            vectors = np.stack([vec_by_id[cid] for cid in doc_ids], axis=0).astype(np.float32, copy=False)
            return (doc_ids, vectors)
        except Exception as exc:
            _log_retriever_fallback("_upsert_colbert_index_incremental", exc)
            return None

    def _upsert_colbert_index_incremental(
        self, *, cache_key: str, corpus_docs: list[Document], upsert_docs: list[Document]
    ) -> None:
        """
        Incrementally update a deterministic dense index for a scope key.

        This updates/overwrites vectors only for `upsert_docs` when an index already exists,
        avoiding a full re-embed of the corpus on each chunk-level upsert.
        """
        if not upsert_docs or not corpus_docs:
            return
        if self._colbert_scope_exceeds_limit(cache_key=cache_key, docs=corpus_docs):
            return
        from app.rag.retrieval.colbert_ann import (
            ColbertAnnIndex,
            ColbertAnnIndexStore,
            build_colbert_provider_config,
            get_dense_embedder,
        )

        provider = self._colbert_provider_name()
        provider_config = self._build_colbert_provider_config(build_colbert_provider_config, provider=provider)
        base_ids, base_vecs = self._colbert_incremental_base_parts(cache_key=cache_key, provider_config=provider_config)
        if not base_ids or base_vecs is None:
            # Keep cold scopes lazy; the reader builds the full corpus when first needed.
            return
        embedder = get_dense_embedder(provider=provider, deterministic_dim=settings.COLBERT_RETRIEVAL_EMBED_DIM or 64)
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
            doc_ids=doc_ids, vectors=vectors, corpus_fingerprint=expected_fp, provider_config=dict(provider_config)
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

    def _remove_colbert_vectors_for_deleted_chunks(
        self, *, scope_key: str, removed_ids: set[str], filtered: list[Document]
    ) -> None:
        if not removed_ids or not settings.COLBERT_RETRIEVAL_ENABLED:
            return
        try:
            with self._get_colbert_build_lock(scope_key):
                idx = self._colbert_index_cache.get(scope_key)
                if idx is None:
                    return
                ids0 = list(idx.doc_ids or [])
                vecs0 = idx.vectors
                if not ids0 or vecs0 is None:
                    return
                self._replace_colbert_index_without_deleted_chunks(
                    scope_key=scope_key, idx=idx, ids0=ids0, vecs0=vecs0, removed_ids=removed_ids, filtered=filtered
                )
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _replace_colbert_index_without_deleted_chunks(
        self,
        *,
        scope_key: str,
        idx: "ColbertAnnIndex",
        ids0: list[str],
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
            from app.rag.retrieval.colbert_ann import ColbertAnnIndex

            self._colbert_index_cache[scope_key] = ColbertAnnIndex(
                doc_ids=new_ids,
                vectors=new_mat,
                corpus_fingerprint=fp,
                provider_config=dict(idx.provider_config or {}),
            )
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    @staticmethod
    def _colbert_index_matches(
        index: "ColbertAnnIndex | None", *, expected_fp: str, provider_config: dict[str, Any]
    ) -> bool:
        try:
            return (
                index is not None
                and str(index.corpus_fingerprint or "") == str(expected_fp or "")
                and (dict(index.provider_config or {}) == dict(provider_config))
            )
        except (TypeError, ValueError, AttributeError):
            return False

    def _load_colbert_index_from_store(
        self, *, store_cls: Any, cache_key: str, provider_config: dict[str, Any], expected_fp: str
    ) -> "ColbertAnnIndex | None":
        if not settings.COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED:
            return None
        try:
            store = store_cls(base_dir=str(settings.COLBERT_RETRIEVAL_INDEX_DIR or ""))
            loaded = store.load(cache_key=cache_key, provider_config=provider_config, expected_fingerprint=expected_fp)
            if loaded is not None:
                self._colbert_index_cache[cache_key] = loaded
            return loaded
        except Exception as exc:
            _log_retriever_fallback("_search_colbert_dense", exc)
            return None

    def _ensure_colbert_search_index(
        self, *, cache_key: str, docs: list[Document], provider_config: dict[str, Any], expected_fp: str, store_cls: Any
    ) -> "ColbertAnnIndex | None":
        index = self._colbert_index_cache.get(cache_key)
        if self._colbert_index_matches(index, expected_fp=expected_fp, provider_config=provider_config):
            return index
        loaded = self._load_colbert_index_from_store(
            store_cls=store_cls, cache_key=cache_key, provider_config=provider_config, expected_fp=expected_fp
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
            _log_retriever_fallback("_search_colbert_dense", exc)
            raise
        return None

    def clear_scope(self, cache_key: str) -> None:
        with self._get_colbert_build_lock(cache_key):
            self._colbert_index_cache.pop(cache_key, None)

    def clear(self) -> None:
        self._colbert_index_cache.clear()
        self._colbert_build_locks.clear()


@dataclass(frozen=True)
class CorpusArtifacts:
    sparse: SparseCorpusIndex
    colbert: ColbertCorpusIndex


def get_corpus_artifacts() -> CorpusArtifacts:
    from app.rag.retrieval.corpus_index import get_corpus_index

    return get_corpus_index().artifacts
