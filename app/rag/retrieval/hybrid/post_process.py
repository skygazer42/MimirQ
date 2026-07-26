"""Post-retrieval result processing for the hybrid retriever.

Split out of ``app.rag.retriever`` (see ``app.rag.retrieval.hybrid``): DB
metadata enrichment, neighbor expansion, continuity stitching, parent-child
auto-merge, and metadata exact-anchor post ordering. Methods run on the
``HybridRetriever`` instance via mixin inheritance; sessions are opened via
``self._open_session()`` so monkeypatches on ``app.rag.retriever.SessionLocal``
keep working.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import or_, tuple_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.retrieval.context_expansion import expand_ranked_chunk_results
from app.rag.retrieval.hybrid.common import (
    _RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY,
    NON_CRITICAL_RETRIEVER_FALLBACK_LOG,
    _apply_metadata_exact_anchor_to_result,
    _float_or_default,
    _log_retriever_fallback,
    logger,
)
from app.rag.retrieval.sibling_expand import select_document_expansion_mode
from app.rag.retrieval.source_labels import derive_document_title, should_replace_source_label
from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig


class PostProcessMixin:
    """Enrichment, neighbor expansion, stitching, parent-child merge, exact-anchor ordering."""

    def _enrich_results_with_db_metadata(
        self,
        results: list[dict[str, Any]],
        *,
        stats: dict[str, Any] | None = None,
        _stats: dict[str, Any] | None = None,
        metadata_filter_override: dict[str, Any] | None = None,
        embedding_runtime: DatasetEmbeddingRuntimeConfig | None = None,
    ) -> list[dict[str, Any]]:
        """
        Vector store may return "trimmed" metadata (e.g., without img_id).
        Use chunk_id / (document_id, chunk_index) to look up DB and fill in key fields:
        - img_id: For MinIO image display
        - page/source: For context annotation (keeping consistent with DB)
        """
        if not results:
            return results

        stats0 = _stats if _stats is not None else stats
        if stats0 is not None:
            stats0.clear()
            stats0["input_results"] = len(results)
            stats0["filtered_orphaned"] = 0
            stats0["filtered_acl"] = 0
            stats0["filtered_dataset"] = 0
            stats0["filtered_not_ready"] = 0
            stats0["filtered_embedding_space"] = 0
            stats0["filtered_pipeline_version"] = 0
            stats0["filtered_metadata_filter"] = 0
            stats0["output_results"] = 0
            stats0["exception"] = None

        db: Session | None = None
        try:
            db = self._open_session()
            tenant_filter = self.tenant_id
            account_id = (self.account_id or "").strip() or None
            dataset_filters = {str(dataset_id) for dataset_id in self._explicit_dataset_scope_ids()}
            runtime = embedding_runtime or self._resolve_embedding_runtime(tenant_id=tenant_filter)
            embedding_space = runtime.embedding_space_hash

            chunk_ids: list[UUID] = []
            # First collect existing chunk_ids (prefer using these for lookup)
            for r in results:
                cid = r.get("chunk_id")
                if not cid:
                    meta = r.get("metadata") or {}
                    cid = meta.get("chunk_id")
                if not cid:
                    continue
                try:
                    chunk_ids.append(UUID(str(cid)))
                except (TypeError, ValueError, AttributeError):
                    continue

            chunks_by_id: dict[str, DocumentChunk] = {}
            if chunk_ids:
                q = db.query(DocumentChunk).filter(DocumentChunk.id.in_(chunk_ids))
                if tenant_filter:
                    q = q.filter(DocumentChunk.tenant_id == tenant_filter)
                for ck in q.all():
                    chunks_by_id[str(ck.id)] = ck

            # Batch lookup missing chunk_id by (document_id, chunk_index) to avoid N+1 queries.
            missing_pairs: set[tuple[UUID, int]] = set()
            for r in results:
                cid = r.get("chunk_id")
                if cid and str(cid) in chunks_by_id:
                    continue
                meta = r.get("metadata") or {}
                doc_id = meta.get("document_id")
                chunk_index = meta.get("chunk_index")
                if doc_id is None or chunk_index is None:
                    continue
                try:
                    doc_uuid = UUID(str(doc_id))
                    chunk_idx = int(chunk_index)
                except (TypeError, ValueError, AttributeError):
                    continue
                missing_pairs.add((doc_uuid, chunk_idx))

            chunks_by_pair: dict[tuple[str, int], DocumentChunk] = {}
            if missing_pairs:
                q = db.query(DocumentChunk).filter(
                    tuple_(DocumentChunk.document_id, DocumentChunk.chunk_index).in_(list(missing_pairs))
                )
                if tenant_filter:
                    q = q.filter(DocumentChunk.tenant_id == tenant_filter)
                for ck in q.all():
                    chunks_by_pair[(str(ck.document_id), int(ck.chunk_index))] = ck

            # Document-level user metadata is stored on documents.metadata.user (not per-chunk).
            # Fetch it once per document to enable metadata filtering like `document_user.tags`.
            doc_user_by_id: dict[str, dict[str, Any]] = {}
            doc_dataset_by_id: dict[str, str] = {}
            doc_ready_by_id: dict[str, bool] = {}
            doc_active_pipeline_key_by_id: dict[str, str] = {}
            doc_parse_quality_by_id: dict[str, float] = {}
            doc_filename_by_id: dict[str, str] = {}
            doc_metadata_by_id: dict[str, dict[str, Any]] = {}
            doc_title_by_id: dict[str, str] = {}
            doc_authority_by_id: dict[str, int] = {}
            doc_updated_ts_by_id: dict[str, float] = {}
            doc_publication_by_id: dict[str, str] = {}
            doc_supersedes_by_id: dict[str, str] = {}
            try:
                doc_ids: set[UUID] = set()
                for ck in list(chunks_by_id.values()) + list(chunks_by_pair.values()):
                    if ck and getattr(ck, "document_id", None):
                        doc_ids.add(UUID(str(ck.document_id)))
                if doc_ids:
                    dq = db.query(
                        DBDocument.id,
                        DBDocument.filename,
                        DBDocument.dataset_id,
                        DBDocument.status,
                        DBDocument.doc_metadata,
                        DBDocument.archived_at,
                        DBDocument.disabled_at,
                        DBDocument.publication_status,
                        DBDocument.authority_level,
                        DBDocument.updated_at,
                        DBDocument.created_at,
                        DBDocument.supersedes_document_id,
                    ).filter(DBDocument.id.in_(sorted(doc_ids)))
                    if tenant_filter:
                        dq = dq.filter(DBDocument.tenant_id == tenant_filter)
                    for (
                        doc_id,
                        filename,
                        ds_id,
                        status,
                        doc_meta,
                        archived_at,
                        disabled_at,
                        publication_status,
                        authority_level,
                        updated_at,
                        created_at,
                        supersedes_document_id,
                    ) in dq.all():
                        doc_id_s = str(doc_id)
                        meta0 = doc_meta if isinstance(doc_meta, dict) else {}
                        doc_metadata_by_id[doc_id_s] = dict(meta0)
                        if filename:
                            doc_filename_by_id[doc_id_s] = str(filename)
                        user0 = meta0.get("user") if isinstance(meta0.get("user"), dict) else {}
                        if user0:
                            doc_user_by_id[doc_id_s] = dict(user0)
                        try:
                            doc_authority_by_id[doc_id_s] = max(0, min(100, int(authority_level or 0)))
                        except (TypeError, ValueError, AttributeError):
                            doc_authority_by_id[doc_id_s] = 0
                        updated = updated_at or created_at
                        if updated is not None:
                            try:
                                doc_updated_ts_by_id[doc_id_s] = float(updated.timestamp())
                            except (TypeError, ValueError, AttributeError, OverflowError) as exc:
                                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
                        doc_publication_by_id[doc_id_s] = str(publication_status or "published").strip().lower()
                        if supersedes_document_id is not None:
                            doc_supersedes_by_id[doc_id_s] = str(supersedes_document_id)
                        pq_obj = meta0.get("parse_quality")
                        pq_score_raw = None
                        if isinstance(pq_obj, dict):
                            pq_score_raw = pq_obj.get("score")
                        elif pq_obj is not None:
                            pq_score_raw = pq_obj
                        try:
                            if pq_score_raw is not None:
                                pq_score = float(pq_score_raw)
                                if pq_score < 0.0:
                                    pq_score = 0.0
                                if pq_score > 1.0:
                                    pq_score = 1.0
                                doc_parse_quality_by_id[str(doc_id)] = float(pq_score)
                        except Exception as exc:
                            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
                        if ds_id is not None:
                            doc_dataset_by_id[str(doc_id)] = str(ds_id)

                        # Versioning: compute active pipeline key for candidate-level trimming.
                        ready = (
                            bool(meta0.get("active_pipeline_ready"))
                            if "active_pipeline_ready" in meta0
                            else (str(status or "").lower() == "completed")
                        )
                        if archived_at is not None or disabled_at is not None:
                            ready = False
                        if str(publication_status or "published").strip().lower() != "published":
                            ready = False
                        doc_ready_by_id[str(doc_id)] = bool(ready)

                        active_key = str(meta0.get("active_doc_pipeline_key") or "").strip()
                        if not active_key:
                            active_hash = str(meta0.get("active_pipeline_hash") or meta0.get("pipeline_hash") or "").strip()
                            if active_hash:
                                active_key = f"{doc_id}:{active_hash}"
                        if ready and active_key:
                            doc_active_pipeline_key_by_id[str(doc_id)] = active_key

                    first_chunk_by_doc_id: dict[str, str] = {}
                    try:
                        fq = db.query(DocumentChunk.document_id, DocumentChunk.content).filter(
                            DocumentChunk.document_id.in_(sorted(doc_ids)),
                            DocumentChunk.chunk_index == 0,
                        )
                        if tenant_filter:
                            fq = fq.filter(DocumentChunk.tenant_id == tenant_filter)
                        for doc_id, content in fq.all():
                            first_chunk_by_doc_id[str(doc_id)] = str(content or "")
                    except Exception as exc:
                        logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

                    for doc_id in doc_ids:
                        doc_id_s = str(doc_id)
                        title = derive_document_title(
                            filename=doc_filename_by_id.get(doc_id_s),
                            doc_metadata=doc_metadata_by_id.get(doc_id_s),
                            first_chunk_content=first_chunk_by_doc_id.get(doc_id_s),
                        )
                        if title:
                            doc_title_by_id[doc_id_s] = title
            except Exception as exc:
                _log_retriever_fallback('_enrich_results_with_db_metadata', exc)
                doc_user_by_id = {}
                doc_dataset_by_id = {}
                doc_ready_by_id = {}
                doc_active_pipeline_key_by_id = {}
                doc_parse_quality_by_id = {}
                doc_filename_by_id = {}
                doc_metadata_by_id = {}
                doc_title_by_id = {}
                doc_authority_by_id = {}
                doc_updated_ts_by_id = {}
                doc_publication_by_id = {}
                doc_supersedes_by_id = {}

            # Candidate-level ACL trimming (security trimming) and dataset scoping.
            # This enables "open scope" retrieval (no precomputed allowed_doc_ids list) without leaking data.
            allowed_docs_str: set[str] | None = None
            if tenant_filter and account_id:
                try:
                    from app.services.document_access import get_allowed_document_id_sets

                    candidate_doc_ids: set[UUID] = set()
                    for k in doc_ready_by_id.keys():
                        if not k:
                            continue
                        try:
                            candidate_doc_ids.add(UUID(str(k)))
                        except Exception as exc:
                            _log_retriever_fallback('_enrich_results_with_db_metadata', exc)
                            continue
                    # Reduce work: if we cannot prove a doc is "ready", treat it as non-searchable.
                    ready_doc_ids: set[UUID] = set()
                    for doc_id, ok in doc_ready_by_id.items():
                        if not ok:
                            continue
                        try:
                            ready_doc_ids.add(UUID(str(doc_id)))
                        except Exception as exc:
                            _log_retriever_fallback('_enrich_results_with_db_metadata', exc)
                            continue
                    candidate_doc_ids = candidate_doc_ids & ready_doc_ids if ready_doc_ids else candidate_doc_ids

                    if dataset_filters and doc_dataset_by_id:
                        candidate_doc_ids = {
                            did
                            for did in candidate_doc_ids
                            if str(did) in doc_dataset_by_id and doc_dataset_by_id[str(did)] in dataset_filters
                        }

                    if candidate_doc_ids:
                        allowed_ids, _missing = get_allowed_document_id_sets(
                            db,
                            tenant_filter,
                            account_id,
                            list(candidate_doc_ids),
                            check_member=True,
                        )
                        allowed_docs_str = {str(did) for did in allowed_ids}
                    else:
                        allowed_docs_str = set()
                except Exception as exc:
                    _log_retriever_fallback('_enrich_results_with_db_metadata', exc)
                    # Fail closed: if ACL check fails, do not return potentially sensitive chunks.
                    allowed_docs_str = set()
            elif account_id and not tenant_filter:
                # If caller provided account_id but not tenant_id, fail closed.
                allowed_docs_str = set()

            resolved: list[dict[str, Any]] = []
            for r in results:
                meta = dict(r.get("metadata") or {})
                cid = r.get("chunk_id") or meta.get("chunk_id")
                ck = chunks_by_id.get(str(cid)) if cid else None

                if ck is None:
                    doc_id = meta.get("document_id")
                    chunk_index = meta.get("chunk_index")
                    try:
                        doc_uuid = UUID(str(doc_id))
                        chunk_idx = int(chunk_index)
                    except (TypeError, ValueError, AttributeError):
                        doc_uuid = None
                        chunk_idx = None
                    if doc_uuid is not None and chunk_idx is not None:
                        ck = chunks_by_pair.get((str(doc_uuid), chunk_idx))

                # If we know tenant_id, treat unresolved results as stale (e.g. orphan vectors).
                if ck is None and tenant_filter:
                    if stats0 is not None:
                        stats0["filtered_orphaned"] = int(stats0.get("filtered_orphaned", 0) or 0) + 1
                    continue

                if ck is not None:
                    # Enforce candidate-level dataset/ACL trimming once we know the resolved document_id.
                    doc_id_str = str(ck.document_id)
                    if allowed_docs_str is not None and doc_id_str not in allowed_docs_str:
                        if stats0 is not None:
                            stats0["filtered_acl"] = int(stats0.get("filtered_acl", 0) or 0) + 1
                        continue
                    if dataset_filters:
                        if doc_dataset_by_id.get(doc_id_str) not in dataset_filters:
                            if stats0 is not None:
                                stats0["filtered_dataset"] = int(stats0.get("filtered_dataset", 0) or 0) + 1
                            continue
                    if getattr(ck, "disabled_at", None) is not None:
                        if stats0 is not None:
                            stats0["filtered_not_ready"] = int(stats0.get("filtered_not_ready", 0) or 0) + 1
                        continue
                    if doc_ready_by_id and not doc_ready_by_id.get(doc_id_str, False):
                        if stats0 is not None:
                            stats0["filtered_not_ready"] = int(stats0.get("filtered_not_ready", 0) or 0) + 1
                        continue

                    cid_str = str(ck.id)
                    r["chunk_id"] = cid_str
                    meta["chunk_id"] = cid_str
                    chunks_by_id[cid_str] = ck

                    # Use DB content as the source of truth for downstream citations/highlighting.
                    # Vector backends may store transformed text (e.g., embedding-only prefixes).
                    try:
                        db_content = ck.content or ""
                        if isinstance(db_content, str) and db_content and r.get("content") != db_content:
                            r["content"] = db_content
                    except Exception as exc:
                        logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

                    # Merge DB metadata (only fill empty fields, avoid overwriting vector-side score etc.)
                    stored_meta = dict(ck.doc_metadata or {})
                    # Fill in missing fields from persisted chunk metadata (rich JSONB).
                    for k, v in stored_meta.items():
                        if k not in meta or meta.get(k) in (None, "", [], {}):
                            meta[k] = v
                    if stored_meta.get("embedding_space_hash") and not meta.get("embedding_space_hash"):
                        meta["embedding_space_hash"] = stored_meta.get("embedding_space_hash")
                    if stored_meta.get("img_id") and not meta.get("img_id"):
                        meta["img_id"] = stored_meta.get("img_id")
                    if stored_meta.get("source") and not meta.get("source"):
                        meta["source"] = stored_meta.get("source")
                    doc_filename = doc_filename_by_id.get(doc_id_str)
                    if doc_filename and (
                        not meta.get("filename") or should_replace_source_label(meta.get("filename"), document_id=doc_id_str)
                    ):
                        meta["filename"] = doc_filename
                    if doc_filename and should_replace_source_label(meta.get("source"), document_id=doc_id_str):
                        meta["source"] = doc_filename
                    doc_title = doc_title_by_id.get(doc_id_str)
                    if doc_title and not meta.get("document_title"):
                        meta["document_title"] = doc_title
                    if doc_id_str in doc_authority_by_id:
                        meta["_governance_authority_level"] = doc_authority_by_id[doc_id_str]
                    if doc_id_str in doc_updated_ts_by_id:
                        meta["_governance_updated_ts"] = doc_updated_ts_by_id[doc_id_str]
                    if doc_id_str in doc_publication_by_id:
                        meta["_governance_publication_status"] = doc_publication_by_id[doc_id_str]
                    if doc_id_str in doc_supersedes_by_id:
                        meta["_governance_supersedes_document_id"] = doc_supersedes_by_id[doc_id_str]
                    if (ck.page_number is not None) and not meta.get("page"):
                        meta["page"] = ck.page_number
                    if (ck.page_number is not None) and not meta.get("page_number"):
                        meta["page_number"] = ck.page_number
                    # Position data enables precise UI highlighting / deep-linking.
                    if (ck.start_char is not None) and meta.get("start_char") is None:
                        meta["start_char"] = int(ck.start_char)
                    if (ck.end_char is not None) and meta.get("end_char") is None:
                        meta["end_char"] = int(ck.end_char)
                    if meta.get("chunk_index") is None:
                        try:
                            meta["chunk_index"] = int(getattr(ck, "chunk_index", None))
                        except Exception as exc:
                            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
                    if stored_meta.get("parser_backend") and not meta.get("parser_backend"):
                        meta["parser_backend"] = stored_meta.get("parser_backend")
                    if stored_meta.get("doc_type_kwd") and not meta.get("doc_type_kwd"):
                        meta["doc_type_kwd"] = stored_meta.get("doc_type_kwd")
                    for key in (
                        "header_path",
                        "header_context",
                        "chunk_strategy",
                        "chunk_role",
                        "parent_id",
                        "hierarchy_basis",
                        "hierarchy_level",
                        "hierarchy_node_key",
                        "hierarchy_family_key",
                        "hierarchy_parent_key",
                        "hierarchy_sibling_index",
                        "hierarchy_prev_sibling_key",
                        "hierarchy_next_sibling_key",
                    ):
                        if stored_meta.get(key) and not meta.get(key):
                            meta[key] = stored_meta.get(key)

                    # Attach document-level user metadata for metadata filtering / enterprise search facets.
                    doc_user = doc_user_by_id.get(str(ck.document_id))
                    if doc_user and not meta.get("document_user"):
                        meta["document_user"] = doc_user
                    if meta.get("doc_parse_quality_score") is None:
                        pq_score = doc_parse_quality_by_id.get(str(ck.document_id))
                        if pq_score is not None:
                            meta["doc_parse_quality_score"] = float(pq_score)

                    # Embedding space guard (vector only): avoid mixing vectors created with different
                    # embedding models/providers/endpoints.
                    #
                    # Notes:
                    # - We only enforce this when the hit came from vector search (Milvus attaches
                    #   `metadata.score`), because BM25 is embedding-space agnostic.
                    # - Legacy vector metadata may omit the hash, but DB metadata must recover a
                    #   matching value before the candidate is allowed through.
                    expected_embedding_space = str(
                        meta.get(_RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY) or embedding_space or ""
                    ).strip()
                    if meta.get(_RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY) is not None or meta.get("score") is not None:
                        ck_space = str(meta.get("embedding_space_hash") or "").strip()
                        if expected_embedding_space and ck_space != expected_embedding_space:
                            if stats0 is not None:
                                stats0["filtered_embedding_space"] = (
                                    int(stats0.get("filtered_embedding_space", 0) or 0) + 1
                                )
                            continue

                    # Candidate-level active pipeline trimming (avoid mixing versions when open-scoped).
                    active_key = doc_active_pipeline_key_by_id.get(doc_id_str)
                    if active_key:
                        ck_key = str(meta.get("doc_pipeline_key") or "").strip()
                        if not ck_key:
                            # Best-effort fallback from pipeline_hash.
                            ph = str(meta.get("pipeline_hash") or stored_meta.get("pipeline_hash") or "").strip()
                            if ph:
                                ck_key = f"{ck.document_id}:{ph}"
                        if not ck_key or ck_key != active_key:
                            if stats0 is not None:
                                stats0["filtered_pipeline_version"] = (
                                    int(stats0.get("filtered_pipeline_version", 0) or 0) + 1
                                )
                            continue

                r["metadata"] = meta
                resolved.append(r)

            # Apply the full metadata filter *after* DB enrichment.
            effective_metadata_filter = metadata_filter_override if metadata_filter_override is not None else self.metadata_filter
            if effective_metadata_filter and self.metadata_filter_enabled:
                try:
                    before = len(resolved)
                    from app.rag.core.filters import apply_metadata_filter_with_stats  # noqa: WPS433

                    resolved, mf_stats = apply_metadata_filter_with_stats(resolved, effective_metadata_filter)
                    blocked = int(mf_stats.get("blocked") or max(0, before - len(resolved)))
                    matched = int(mf_stats.get("matched") or len(resolved))
                    summary = mf_stats.get("summary") if isinstance(mf_stats.get("summary"), dict) else None
                    if stats0 is not None:
                        stats0["filtered_metadata_filter"] = int(blocked)
                        stats0["metadata_filter_blocked"] = int(blocked)
                        stats0["metadata_filter_matched"] = int(matched)
                        if summary:
                            stats0["metadata_filter"] = summary
                except Exception as exc:
                    logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
                    if stats0 is not None:
                        stats0["exception"] = str(exc)[:200]
                        stats0["output_results"] = 0
                    return []

            if stats0 is not None:
                stats0["output_results"] = len(resolved)
            return resolved
        except Exception as exc:
            _log_retriever_fallback('_enrich_results_with_db_metadata', exc)
            if stats0 is not None:
                stats0["exception"] = str(exc)[:200]
            return []
        finally:
            try:
                if db is not None:
                    db.close()
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _expand_results_with_neighbors(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Optionally attach adjacent chunks around top hits for better continuity."""
        if not results:
            return results

        window_raw = (
            self.context_neighbor_window
            if self.context_neighbor_window is not None
            else getattr(settings, "RAG_CONTEXT_NEIGHBOR_WINDOW", 0)
        )
        window = max(0, int(window_raw or 0))
        sibling_enabled = bool(getattr(settings, "RAG_CONTEXT_SIBLING_EXPAND_ENABLED", False))
        short_doc_max_chunks = max(0, int(getattr(settings, "RAG_CONTEXT_SIBLING_SHORT_DOC_MAX_CHUNKS", 0) or 0))
        if window <= 0 and not (sibling_enabled and short_doc_max_chunks > 0):
            return results

        max_added_raw = (
            self.context_neighbor_max_added
            if self.context_neighbor_max_added is not None
            else getattr(settings, "RAG_CONTEXT_NEIGHBOR_MAX_ADDED", 0)
        )
        max_added = max(0, int(max_added_raw or 0))
        sibling_max_added = max(
            0,
            int(settings.RAG_CONTEXT_SIBLING_MAX_ADDED),
        )
        tenant_filter = self.tenant_id

        # Version-aware neighbor fetch:
        # - Some installations keep multiple pipeline versions in `document_chunks`.
        # - We must avoid pulling neighbors from an inactive pipeline version, even for the same document.
        desired_pipeline_by_doc: dict[str, str] = {}

        anchors: list[tuple[dict[str, Any], UUID | None, int | None, str | None]] = []
        for r in results:
            meta = r.get("metadata") or {}
            doc_id = meta.get("document_id")
            chunk_index = meta.get("chunk_index")
            try:
                doc_uuid = UUID(str(doc_id)) if doc_id is not None else None
                idx = int(chunk_index) if chunk_index is not None else None
            except (TypeError, ValueError, AttributeError):
                doc_uuid = None
                idx = None
            pipeline_key = str(meta.get("doc_pipeline_key") or "").strip()
            if not pipeline_key and doc_uuid is not None:
                ph = str(meta.get("pipeline_hash") or "").strip()
                if ph:
                    pipeline_key = f"{doc_uuid}:{ph}"
            pipeline_key = pipeline_key or None
            if doc_uuid is not None and pipeline_key:
                desired_pipeline_by_doc.setdefault(str(doc_uuid), pipeline_key)
            anchors.append((r, doc_uuid, idx, pipeline_key))

        document_chunks_by_doc: dict[str, list[DocumentChunk]] = {}
        short_doc_ids: set[str] = set()
        doc_ids_for_sibling = {doc_uuid for _, doc_uuid, _, _ in anchors if doc_uuid is not None}

        needed_pairs: set[tuple[UUID, int]] = set()
        for _, doc_uuid, idx, _pk in anchors:
            if doc_uuid is not None and str(doc_uuid) in short_doc_ids:
                continue
            if doc_uuid is None or idx is None:
                continue
            for delta in range(-window, window + 1):
                if delta == 0:
                    continue
                neighbor_idx = idx + delta
                if neighbor_idx < 0:
                    continue
                needed_pairs.add((doc_uuid, neighbor_idx))

        if not needed_pairs:
            return results

        neighbors_by_pair: dict[tuple[str, int], DocumentChunk] = {}
        db = self._open_session()
        try:
            if sibling_enabled and short_doc_max_chunks > 0 and doc_ids_for_sibling:
                q_all = db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(list(doc_ids_for_sibling)))
                if tenant_filter:
                    q_all = q_all.filter(DocumentChunk.tenant_id == tenant_filter)
                for ck in q_all.all():
                    doc_key = str(ck.document_id)
                    desired = desired_pipeline_by_doc.get(doc_key)
                    if desired:
                        stored_meta = dict(getattr(ck, "doc_metadata", None) or {})
                        ck_key = str(stored_meta.get("doc_pipeline_key") or "").strip()
                        if not ck_key:
                            ph = str(stored_meta.get("pipeline_hash") or "").strip()
                            if ph:
                                ck_key = f"{ck.document_id}:{ph}"
                        if not ck_key or ck_key != desired:
                            continue
                    document_chunks_by_doc.setdefault(doc_key, []).append(ck)
                short_doc_ids = {
                    doc_key
                    for doc_key, rows in document_chunks_by_doc.items()
                    if select_document_expansion_mode(
                        total_chunks=len(rows),
                        short_doc_max_chunks=short_doc_max_chunks,
                    )
                    == "sibling"
                }

            q = db.query(DocumentChunk).filter(
                tuple_(DocumentChunk.document_id, DocumentChunk.chunk_index).in_(list(needed_pairs))
            )
            if tenant_filter:
                q = q.filter(DocumentChunk.tenant_id == tenant_filter)
            for ck in q.all():
                doc_key = str(ck.document_id)
                desired = desired_pipeline_by_doc.get(doc_key)
                if desired:
                    stored_meta = dict(getattr(ck, "doc_metadata", None) or {})
                    ck_key = str(stored_meta.get("doc_pipeline_key") or "").strip()
                    if not ck_key:
                        ph = str(stored_meta.get("pipeline_hash") or "").strip()
                        if ph:
                            ck_key = f"{ck.document_id}:{ph}"
                    if not ck_key or ck_key != desired:
                        continue
                neighbors_by_pair[(doc_key, int(ck.chunk_index))] = ck
        except Exception as exc:
            _log_retriever_fallback('_expand_results_with_neighbors', exc)
            return results
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

        original_results_by_chunk_id: dict[str, dict[str, Any]] = {}
        for r in results:
            cid = r.get("chunk_id") or (r.get("metadata") or {}).get("chunk_id")
            if cid:
                original_results_by_chunk_id[str(cid)] = r
        expanded, _meta = expand_ranked_chunk_results(
            results=results,
            window=window,
            max_added=max_added,
            sibling_max_added=sibling_max_added,
            document_chunks_by_doc=document_chunks_by_doc,
            short_doc_ids=short_doc_ids,
            neighbors_by_pair=neighbors_by_pair,
            original_results_by_chunk_id=original_results_by_chunk_id,
            score_driven=bool(self.context_neighbor_score_driven),
            high_threshold=float(
                self.context_neighbor_high_threshold
                if self.context_neighbor_high_threshold is not None
                else 0.7
            ),
            mid_threshold=float(
                self.context_neighbor_mid_threshold
                if self.context_neighbor_mid_threshold is not None
                else 0.4
            ),
            high_span=max(0, int(self.context_neighbor_high_span if self.context_neighbor_high_span is not None else window)),
            mid_span=max(0, int(self.context_neighbor_mid_span if self.context_neighbor_mid_span is not None else 1)),
        )
        return expanded

    @staticmethod
    def _stitching_score(result: dict[str, Any]) -> float:
        try:
            return float(result.get("score") or 0.0)
        except (TypeError, ValueError, AttributeError):
            return 0.0

    @classmethod
    def _split_stitchable_results(
        cls,
        results: list[dict[str, Any]],
    ) -> tuple[dict[str, list[tuple[int, int, dict[str, Any]]]], list[tuple[float, int, list[dict[str, Any]]]]]:
        stitchable_by_doc: dict[str, list[tuple[int, int, dict[str, Any]]]] = {}
        singleton_groups: list[tuple[float, int, list[dict[str, Any]]]] = []

        for pos, result in enumerate(results):
            meta = result.get("metadata") or {}
            doc_id = meta.get("document_id")
            chunk_index = meta.get("chunk_index")
            doc_key = str(doc_id).strip() if doc_id is not None else ""
            try:
                idx = int(chunk_index) if chunk_index is not None else None
            except (TypeError, ValueError, AttributeError):
                idx = None
            if doc_key and idx is not None and idx >= 0:
                stitchable_by_doc.setdefault(doc_key, []).append((idx, pos, result))
                continue
            singleton_groups.append((cls._stitching_score(result), pos, [result]))

        return stitchable_by_doc, singleton_groups

    @classmethod
    def _append_stitched_run(
        cls,
        groups: list[tuple[float, str, int, int, int, list[dict[str, Any]]]],
        *,
        doc_id: str,
        run: list[tuple[int, int, dict[str, Any]]],
    ) -> None:
        if not run:
            return
        run_score = max(cls._stitching_score(x[2]) for x in run)
        start_idx = int(run[0][0])
        end_idx = int(run[-1][0])
        min_pos = min(int(x[1]) for x in run)
        groups.append((run_score, doc_id, start_idx, end_idx, min_pos, [x[2] for x in run]))

    @classmethod
    def _stitching_groups_for_doc(
        cls,
        *,
        doc_id: str,
        entries: list[tuple[int, int, dict[str, Any]]],
    ) -> list[tuple[float, str, int, int, int, list[dict[str, Any]]]]:
        groups: list[tuple[float, str, int, int, int, list[dict[str, Any]]]] = []
        entries.sort(key=lambda t: (t[0], t[1]))
        run: list[tuple[int, int, dict[str, Any]]] = []

        for idx, pos, result in entries:
            if not run:
                run = [(idx, pos, result)]
                continue
            if idx == run[-1][0] + 1:
                run.append((idx, pos, result))
                continue
            cls._append_stitched_run(groups, doc_id=doc_id, run=run)
            run = [(idx, pos, result)]

        cls._append_stitched_run(groups, doc_id=doc_id, run=run)
        return groups

    @classmethod
    def _build_stitching_groups(
        cls,
        *,
        stitchable_by_doc: dict[str, list[tuple[int, int, dict[str, Any]]]],
        singleton_groups: list[tuple[float, int, list[dict[str, Any]]]],
    ) -> list[tuple[float, str, int, int, int, list[dict[str, Any]]]]:
        groups: list[tuple[float, str, int, int, int, list[dict[str, Any]]]] = []
        for doc_id, entries in stitchable_by_doc.items():
            groups.extend(cls._stitching_groups_for_doc(doc_id=doc_id, entries=entries))

        # Add singleton groups (no document_id/chunk_index); keep them sortable by score with stable tie-breakers.
        for score, pos, items in singleton_groups:
            groups.append((float(score), "", -1, -1, int(pos), items))
        return groups

    def _stitch_results_for_continuity(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Reorder results to improve continuity by stitching contiguous chunk ranges.

        This is order-only: it never drops or adds results.

        Why:
        - Retrieval pipelines often return chunks in score order, which can interleave documents
          and fragment contiguous passages.
        - For prompt context (and UI previews), grouping contiguous chunks improves readability
          and reduces "jumping around" in the source material.
        """
        if not results:
            return results
        if not bool(getattr(settings, "RAG_CONTEXT_STITCHING_ENABLED", False)):
            return results

        stitchable_by_doc, singleton_groups = self._split_stitchable_results(results)
        groups = self._build_stitching_groups(
            stitchable_by_doc=stitchable_by_doc,
            singleton_groups=singleton_groups,
        )

        # Sort stitched groups by their max relevance score, then deterministic tie-breakers.
        groups.sort(key=lambda g: (-float(g[0]), str(g[1]), int(g[2]), int(g[4])))

        stitched: list[dict[str, Any]] = []
        for _score_g, _doc_id, _start, _end, _pos, items in groups:
            stitched.extend(items)

        return stitched

    def _auto_merge_parent_child(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Parent-child auto merge (LlamaIndex AutoMergingRetriever-style, simplified).

        - When results contain many child hits for the same parent_id, collapse them into the parent chunk.
        - Two modes:
          - replace: drop children (and their neighbors) and insert/bump the parent once.
          - append: keep children and insert the parent once (deduped).
        """
        if not results:
            return results
        if not bool(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_ENABLED", False)):
            return results

        mode = str(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_MODE", "replace") or "replace").strip().lower()
        if mode not in {"replace", "append"}:
            mode = "replace"

        min_children = max(1, int(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_MIN_CHILDREN", 2) or 2))
        max_parents = max(0, int(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_MAX_PARENTS", 20) or 20))

        tenant_filter = self.tenant_id

        # Group child hits by (document_id, family collapse key).
        child_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        parent_results: dict[tuple[str, str], dict[str, Any]] = {}

        # For neighbor cleanup (replace mode).
        child_chunk_ids_by_group: dict[tuple[str, str], set[str]] = {}

        for r in results:
            meta = r.get("metadata") or {}
            role = str(meta.get("chunk_role") or "").strip().lower()
            doc_id = str(meta.get("document_id") or "").strip()
            family_key = self._resolve_family_collapse_key(meta, result=r)
            if not family_key or not doc_id:
                continue

            cid = r.get("chunk_id") or meta.get("chunk_id")
            cid_str = str(cid) if cid else ""

            if role == "parent":
                parent_results[(doc_id, family_key)] = r
            elif role == "child":
                key = (doc_id, family_key)
                child_groups.setdefault(key, []).append(r)
                if cid_str:
                    child_chunk_ids_by_group.setdefault(key, set()).add(cid_str)

        if not child_groups:
            return results

        # Version-aware parent materialization: only pull parent chunks from the same active pipeline
        # version as the retrieved children.
        desired_pipeline_by_doc: dict[str, str] = {}
        for r in results:
            meta = r.get("metadata") or {}
            doc_id = str(meta.get("document_id") or "").strip()
            if not doc_id:
                continue
            pipeline_key = str(meta.get("doc_pipeline_key") or "").strip()
            if not pipeline_key:
                ph = str(meta.get("pipeline_hash") or "").strip()
                if ph:
                    pipeline_key = f"{doc_id}:{ph}"
            if pipeline_key:
                desired_pipeline_by_doc.setdefault(doc_id, pipeline_key)

        # Select top groups (by best child score) to avoid excessive DB queries.
        scored_groups: list[tuple[float, tuple[str, str]]] = []
        for key, items in child_groups.items():
            best = 0.0
            for it in items:
                try:
                    best = max(best, float(it.get("score", 0.0) or 0.0))
                except (TypeError, ValueError, AttributeError):
                    continue
            scored_groups.append((best, key))
        scored_groups.sort(key=lambda x: x[0], reverse=True)
        if max_parents and len(scored_groups) > max_parents:
            scored_groups = scored_groups[:max_parents]

        # Decide which groups to materialize a parent for.
        selected_keys: list[tuple[str, str]] = []
        for _, key in scored_groups:
            if mode == "replace" and len(child_groups.get(key) or []) < min_children:
                continue
            selected_keys.append(key)

        if not selected_keys:
            return results

        # Fetch parent chunks not already present in results.
        missing_keys = [k for k in selected_keys if k not in parent_results]
        fetched_parents: dict[tuple[str, str], DocumentChunk] = {}

        if missing_keys:
            doc_ids: set[UUID] = set()
            family_keys: set[str] = set()
            for doc_id, family_key in missing_keys:
                try:
                    doc_ids.add(UUID(doc_id))
                except Exception as exc:
                    _log_retriever_fallback('_auto_merge_parent_child', exc)
                    continue
                if family_key:
                    family_keys.add(family_key)

            if doc_ids and family_keys:
                db = self._open_session()
                try:
                    q = db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(list(doc_ids)))
                    if tenant_filter:
                        q = q.filter(DocumentChunk.tenant_id == tenant_filter)
                    # Prefer hierarchy_family_key and keep parent_id as a backward-compatible fallback.
                    q = q.filter(DocumentChunk.doc_metadata["chunk_role"].astext == "parent")  # type: ignore[attr-defined]
                    q = q.filter(
                        or_(
                            DocumentChunk.doc_metadata["hierarchy_family_key"].astext.in_(list(family_keys)),  # type: ignore[attr-defined]
                            DocumentChunk.doc_metadata["parent_id"].astext.in_(list(family_keys)),  # type: ignore[attr-defined]
                        )
                    )
                    for ck in q.all():
                        meta = dict(getattr(ck, "doc_metadata", None) or {})
                        family_key = self._resolve_family_collapse_key(meta)
                        if not family_key:
                            continue
                        desired = desired_pipeline_by_doc.get(str(ck.document_id))
                        if desired:
                            ck_key = str(meta.get("doc_pipeline_key") or "").strip()
                            if not ck_key:
                                ph = str(meta.get("pipeline_hash") or "").strip()
                                if ph:
                                    ck_key = f"{ck.document_id}:{ph}"
                            if not ck_key or ck_key != desired:
                                continue
                        fetched_parents[(str(ck.document_id), family_key)] = ck
                except Exception as exc:
                    _log_retriever_fallback('_auto_merge_parent_child', exc)
                    fetched_parents = {}
                finally:
                    try:
                        db.close()
                    except Exception as exc:
                        logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

        # Helper: materialize a parent result dict.
        def _parent_result_for(key: tuple[str, str], *, best_child_score: float) -> dict[str, Any] | None:
            if key in parent_results:
                # If parent is already present (e.g., neighbor expansion), bump its score and mark role.
                existing = parent_results[key]
                meta = dict(existing.get("metadata") or {})
                meta["retrieval_role"] = "parent"
                existing["metadata"] = meta
                try:
                    existing_score = float(existing.get("score", 0.0) or 0.0)
                except (TypeError, ValueError, AttributeError):
                    existing_score = 0.0
                existing["score"] = max(existing_score, best_child_score * 0.97)
                return existing

            ck = fetched_parents.get(key)
            if ck is None:
                return None

            cid = str(ck.id)
            stored_meta = dict(ck.doc_metadata or {})
            stored_meta.setdefault("tenant_id", str(ck.tenant_id))
            stored_meta.setdefault("document_id", str(ck.document_id))
            stored_meta.setdefault("chunk_index", int(ck.chunk_index))
            stored_meta.setdefault("chunk_id", cid)
            if ck.page_number is not None:
                stored_meta.setdefault("page", ck.page_number)
            if not stored_meta.get("source"):
                stored_meta["source"] = "unknown"
            stored_meta["retrieval_role"] = "parent"

            return {
                "chunk_id": cid,
                "content": ck.content,
                "metadata": stored_meta,
                "score": float(best_child_score * 0.97),
            }

        # Build quick access for best child score per group.
        best_score_by_group: dict[tuple[str, str], float] = {}
        for key in selected_keys:
            best = 0.0
            for it in child_groups.get(key) or []:
                try:
                    best = max(best, float(it.get("score", 0.0) or 0.0))
                except (TypeError, ValueError, AttributeError):
                    continue
            best_score_by_group[key] = best

        if mode == "append":
            inserted: set[tuple[str, str]] = set()
            out: list[dict[str, Any]] = []
            for r in results:
                out.append(r)
                meta = r.get("metadata") or {}
                role = str(meta.get("chunk_role") or "").strip().lower()
                if role != "child":
                    continue
                key = (
                    str(meta.get("document_id") or "").strip(),
                    self._resolve_family_collapse_key(meta, result=r),
                )
                if key not in selected_keys or key in inserted:
                    continue
                # Parent already present in results (e.g., neighbor expansion) -> don't duplicate.
                if key in parent_results:
                    inserted.add(key)
                    continue
                # Only insert if we can materialize the parent.
                parent = _parent_result_for(key, best_child_score=best_score_by_group.get(key, 0.0))
                if parent is not None:
                    out.append(parent)
                    inserted.add(key)
            return out

        # replace mode: collapse groups.
        to_replace = set(selected_keys)
        removed_child_ids: set[str] = set()
        for key in to_replace:
            removed_child_ids |= child_chunk_ids_by_group.get(key, set())

        inserted: set[tuple[str, str]] = set()
        out: list[dict[str, Any]] = []
        for r in results:
            meta = r.get("metadata") or {}
            cid = r.get("chunk_id") or meta.get("chunk_id")
            cid_str = str(cid) if cid else ""

            # Drop neighbors that were added for removed children.
            if meta.get("retrieval_role") == "neighbor":
                if str(meta.get("neighbor_of") or "") in removed_child_ids:
                    continue

            role = str(meta.get("chunk_role") or "").strip().lower()
            key = (
                str(meta.get("document_id") or "").strip(),
                self._resolve_family_collapse_key(meta, result=r),
            )

            if role == "child" and key in to_replace:
                if key in inserted:
                    continue
                parent = _parent_result_for(key, best_child_score=best_score_by_group.get(key, 0.0))
                if parent is not None:
                    out.append(parent)
                inserted.add(key)
                continue

            # If parent is already present, keep it (and mark as parent role).
            if role == "parent" and key in to_replace:
                pr = _parent_result_for(key, best_child_score=best_score_by_group.get(key, 0.0))
                if pr is not None:
                    # Ensure we only keep one parent per group.
                    if key in inserted:
                        continue
                    out.append(pr)
                    inserted.add(key)
                    continue

            # Keep other results as-is.
            if cid_str and cid_str in removed_child_ids and role == "child":
                continue
            out.append(r)

        return out

    def _apply_metadata_exact_anchor_post_ordering(
        self,
        query: str,
        results: list[dict[str, Any]],
        *,
        stats: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not query or not results:
            if stats is not None:
                stats["applied"] = False
                stats["reason"] = "empty"
            return results

        phrase_boost_weight = max(
            0.0,
            float(getattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35) or 0.0),
        )
        annotated: list[tuple[dict[str, Any], int]] = []
        annotated_count = 0
        promoted_count = 0
        has_budgeted_prefix = any(
            isinstance(result, dict) and result.get("fusion_budgeted_prefix_rank") is not None
            for result in results
        )
        for pos, result in enumerate(results):
            item = dict(result)
            changed = _apply_metadata_exact_anchor_to_result(
                query=query,
                result=item,
                phrase_boost_weight=phrase_boost_weight,
                promote_score=True,
            )
            if changed:
                annotated_count += 1
                if item.get("metadata_exact_match_promoted_score") is not None:
                    promoted_count += 1
            else:
                item = result
            annotated.append((item, pos))

        if annotated_count <= 0:
            if stats is not None:
                stats["applied"] = False
                stats["annotated"] = 0
            return results

        before_top = self._result_key(annotated[0][0]) if annotated else ""
        best_anchor_score = max(
            _float_or_default(item.get("metadata_exact_match_score"), 0.0) for item, _pos in annotated
        )

        def sort_key(pair: tuple[dict[str, Any], int]) -> tuple[float, float, int]:
            item, pos = pair
            if has_budgeted_prefix:
                try:
                    prefix_rank = int(item.get("fusion_budgeted_prefix_rank"))
                except (TypeError, ValueError):
                    prefix_rank = len(results) + int(pos) + 1
                return (
                    float(prefix_rank),
                    -_float_or_default(item.get("metadata_exact_match_score"), 0.0),
                    int(pos),
                )
            if best_anchor_score >= 0.65:
                return (
                    -_float_or_default(item.get("metadata_exact_match_score"), 0.0),
                    -_float_or_default(item.get("score"), 0.0),
                    int(pos),
                )
            return (
                -_float_or_default(item.get("score"), 0.0),
                -_float_or_default(item.get("metadata_exact_match_score"), 0.0),
                int(pos),
            )

        annotated.sort(key=sort_key)
        ordered = [item for item, _pos in annotated]
        after_top = self._result_key(ordered[0]) if ordered else ""
        if stats is not None:
            stats["applied"] = True
            stats["annotated"] = int(annotated_count)
            stats["score_promoted"] = int(promoted_count)
            stats["top_changed"] = bool(before_top and after_top and before_top != after_top)
        return ordered
