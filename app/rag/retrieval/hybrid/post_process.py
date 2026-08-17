"""Post-retrieval result processing for the hybrid retriever.

Split out of ``app.rag.retriever`` (see ``app.rag.retrieval.hybrid``): DB
metadata enrichment, neighbor expansion, continuity stitching, parent-child
auto-merge, and metadata exact-anchor post ordering. Methods run on the
``HybridRetriever`` instance via mixin inheritance; sessions are opened via
``self._open_session()`` so monkeypatches on ``app.rag.retriever.SessionLocal``
keep working.
"""

from dataclasses import dataclass, field
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


@dataclass
class _DocumentEnrichmentContext:
    doc_user_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    doc_dataset_by_id: dict[str, str] = field(default_factory=dict)
    doc_ready_by_id: dict[str, bool] = field(default_factory=dict)
    doc_active_pipeline_key_by_id: dict[str, str] = field(default_factory=dict)
    doc_parse_quality_by_id: dict[str, float] = field(default_factory=dict)
    doc_filename_by_id: dict[str, str] = field(default_factory=dict)
    doc_metadata_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    doc_title_by_id: dict[str, str] = field(default_factory=dict)
    doc_authority_by_id: dict[str, int] = field(default_factory=dict)
    doc_updated_ts_by_id: dict[str, float] = field(default_factory=dict)
    doc_publication_by_id: dict[str, str] = field(default_factory=dict)
    doc_supersedes_by_id: dict[str, str] = field(default_factory=dict)


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
        self._reset_enrichment_stats(stats0, input_results=len(results))

        db: Session | None = None
        try:
            db = self._open_session()
            tenant_filter, account_id, dataset_filters, embedding_space = self._enrichment_runtime_state(
                embedding_runtime=embedding_runtime,
            )
            chunks_by_id = self._load_enrichment_chunks_by_id(db, results, tenant_filter=tenant_filter)
            chunks_by_pair = self._load_enrichment_chunks_by_pair(
                db,
                results,
                chunks_by_id=chunks_by_id,
                tenant_filter=tenant_filter,
            )
            doc_ctx = self._load_document_enrichment_context(
                db,
                chunks_by_id=chunks_by_id,
                chunks_by_pair=chunks_by_pair,
                tenant_filter=tenant_filter,
            )
            allowed_docs_str = self._resolve_allowed_docs_for_enrichment(
                db,
                tenant_filter=tenant_filter,
                account_id=account_id,
                dataset_filters=dataset_filters,
                doc_ctx=doc_ctx,
            )
            resolved = self._resolve_enriched_results(
                results,
                chunks_by_id=chunks_by_id,
                chunks_by_pair=chunks_by_pair,
                doc_ctx=doc_ctx,
                allowed_docs_str=allowed_docs_str,
                dataset_filters=dataset_filters,
                embedding_space=embedding_space,
                stats0=stats0,
            )
            resolved = self._apply_enrichment_metadata_filter(
                resolved,
                metadata_filter_override=metadata_filter_override,
                stats0=stats0,
            )
            if stats0 is not None:
                stats0["output_results"] = len(resolved)
            return resolved
        except Exception as exc:
            _log_retriever_fallback("_enrich_results_with_db_metadata", exc)
            if stats0 is not None:
                stats0["exception"] = str(exc)[:200]
            return []
        finally:
            try:
                if db is not None:
                    db.close()
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    @staticmethod
    def _reset_enrichment_stats(stats0: dict[str, Any] | None, *, input_results: int) -> None:
        if stats0 is None:
            return
        stats0.clear()
        stats0.update(
            {
                "input_results": input_results,
                "filtered_orphaned": 0,
                "filtered_acl": 0,
                "filtered_dataset": 0,
                "filtered_not_ready": 0,
                "filtered_embedding_space": 0,
                "filtered_pipeline_version": 0,
                "filtered_metadata_filter": 0,
                "output_results": 0,
                "exception": None,
            }
        )

    def _enrichment_runtime_state(
        self,
        *,
        embedding_runtime: DatasetEmbeddingRuntimeConfig | None,
    ) -> tuple[UUID | None, str | None, set[str], str]:
        tenant_filter = self.tenant_id
        account_id = (self.account_id or "").strip() or None
        dataset_filters = {str(dataset_id) for dataset_id in self._explicit_dataset_scope_ids()}
        runtime = embedding_runtime or self._resolve_embedding_runtime(tenant_id=tenant_filter)
        return tenant_filter, account_id, dataset_filters, str(runtime.embedding_space_hash or "").strip()

    def _load_enrichment_chunks_by_id(
        self,
        db: Session,
        results: list[dict[str, Any]],
        *,
        tenant_filter: UUID | None,
    ) -> dict[str, DocumentChunk]:
        chunk_ids = self._result_chunk_ids(results)
        if not chunk_ids:
            return {}
        q = db.query(DocumentChunk).filter(DocumentChunk.id.in_(chunk_ids))
        if tenant_filter:
            q = q.filter(DocumentChunk.tenant_id == tenant_filter)
        return {str(chunk.id): chunk for chunk in q.all()}

    def _result_chunk_ids(self, results: list[dict[str, Any]]) -> list[UUID]:
        chunk_ids: list[UUID] = []
        for result in results:
            cid = result.get("chunk_id") or (result.get("metadata") or {}).get("chunk_id")
            try:
                if cid:
                    chunk_ids.append(UUID(str(cid)))
            except (TypeError, ValueError, AttributeError):
                continue
        return chunk_ids

    def _load_enrichment_chunks_by_pair(
        self,
        db: Session,
        results: list[dict[str, Any]],
        *,
        chunks_by_id: dict[str, DocumentChunk],
        tenant_filter: UUID | None,
    ) -> dict[tuple[str, int], DocumentChunk]:
        missing_pairs = self._missing_chunk_pairs(results, chunks_by_id=chunks_by_id)
        if not missing_pairs:
            return {}
        q = db.query(DocumentChunk).filter(
            tuple_(DocumentChunk.document_id, DocumentChunk.chunk_index).in_(list(missing_pairs))
        )
        if tenant_filter:
            q = q.filter(DocumentChunk.tenant_id == tenant_filter)
        return {(str(chunk.document_id), int(chunk.chunk_index)): chunk for chunk in q.all()}

    def _missing_chunk_pairs(
        self,
        results: list[dict[str, Any]],
        *,
        chunks_by_id: dict[str, DocumentChunk],
    ) -> set[tuple[UUID, int]]:
        missing_pairs: set[tuple[UUID, int]] = set()
        for result in results:
            cid = result.get("chunk_id")
            if cid and str(cid) in chunks_by_id:
                continue
            meta = result.get("metadata") or {}
            doc_id = meta.get("document_id")
            chunk_index = meta.get("chunk_index")
            try:
                if doc_id is not None and chunk_index is not None:
                    missing_pairs.add((UUID(str(doc_id)), int(chunk_index)))
            except (TypeError, ValueError, AttributeError):
                continue
        return missing_pairs

    def _load_document_enrichment_context(
        self,
        db: Session,
        *,
        chunks_by_id: dict[str, DocumentChunk],
        chunks_by_pair: dict[tuple[str, int], DocumentChunk],
        tenant_filter: UUID | None,
    ) -> _DocumentEnrichmentContext:
        doc_ids = {
            UUID(str(chunk.document_id))
            for chunk in list(chunks_by_id.values()) + list(chunks_by_pair.values())
            if chunk and getattr(chunk, "document_id", None)
        }
        if not doc_ids:
            return _DocumentEnrichmentContext()
        try:
            doc_ctx = self._query_document_enrichment_rows(db, doc_ids=doc_ids, tenant_filter=tenant_filter)
            first_chunk_by_doc_id = self._query_first_chunk_content(
                db,
                doc_ids=doc_ids,
                tenant_filter=tenant_filter,
            )
            self._populate_document_titles(doc_ctx, doc_ids=doc_ids, first_chunk_by_doc_id=first_chunk_by_doc_id)
            return doc_ctx
        except Exception as exc:
            _log_retriever_fallback("_enrich_results_with_db_metadata", exc)
            return _DocumentEnrichmentContext()

    def _query_document_enrichment_rows(
        self,
        db: Session,
        *,
        doc_ids: set[UUID],
        tenant_filter: UUID | None,
    ) -> _DocumentEnrichmentContext:
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
        doc_ctx = _DocumentEnrichmentContext()
        for row in dq.all():
            self._record_document_enrichment_row(doc_ctx, row)
        return doc_ctx

    def _record_document_enrichment_row(
        self,
        doc_ctx: _DocumentEnrichmentContext,
        row: tuple[Any, ...],
    ) -> None:
        (
            doc_id,
            filename,
            dataset_id,
            status,
            doc_meta,
            archived_at,
            disabled_at,
            publication_status,
            authority_level,
            updated_at,
            created_at,
            supersedes_document_id,
        ) = row
        doc_id_s = str(doc_id)
        meta0 = doc_meta if isinstance(doc_meta, dict) else {}
        doc_ctx.doc_metadata_by_id[doc_id_s] = dict(meta0)
        if filename:
            doc_ctx.doc_filename_by_id[doc_id_s] = str(filename)
        user0 = meta0.get("user") if isinstance(meta0.get("user"), dict) else {}
        if user0:
            doc_ctx.doc_user_by_id[doc_id_s] = dict(user0)
        doc_ctx.doc_authority_by_id[doc_id_s] = self._authority_level(authority_level)
        self._record_document_timestamps(
            doc_ctx,
            doc_id_s=doc_id_s,
            updated_at=updated_at,
            created_at=created_at,
        )
        doc_ctx.doc_publication_by_id[doc_id_s] = str(publication_status or "published").strip().lower()
        if supersedes_document_id is not None:
            doc_ctx.doc_supersedes_by_id[doc_id_s] = str(supersedes_document_id)
        self._record_document_parse_quality(doc_ctx, doc_id_s=doc_id_s, doc_meta=meta0)
        if dataset_id is not None:
            doc_ctx.doc_dataset_by_id[doc_id_s] = str(dataset_id)
        ready = self._document_ready(
            status=status,
            doc_meta=meta0,
            archived_at=archived_at,
            disabled_at=disabled_at,
            publication_status=publication_status,
        )
        doc_ctx.doc_ready_by_id[doc_id_s] = bool(ready)
        active_key = self._document_active_pipeline_key(doc_meta=meta0, document_id=str(doc_id))
        if ready and active_key:
            doc_ctx.doc_active_pipeline_key_by_id[doc_id_s] = active_key

    @staticmethod
    def _authority_level(value: Any) -> int:
        try:
            return max(0, min(100, int(value or 0)))
        except (TypeError, ValueError, AttributeError):
            return 0

    def _record_document_timestamps(
        self,
        doc_ctx: _DocumentEnrichmentContext,
        *,
        doc_id_s: str,
        updated_at: Any,
        created_at: Any,
    ) -> None:
        updated = updated_at or created_at
        if updated is None:
            return
        try:
            doc_ctx.doc_updated_ts_by_id[doc_id_s] = float(updated.timestamp())
        except (TypeError, ValueError, AttributeError, OverflowError) as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _record_document_parse_quality(
        self,
        doc_ctx: _DocumentEnrichmentContext,
        *,
        doc_id_s: str,
        doc_meta: dict[str, Any],
    ) -> None:
        pq_obj = doc_meta.get("parse_quality")
        pq_score_raw = pq_obj.get("score") if isinstance(pq_obj, dict) else pq_obj
        if pq_score_raw is None:
            return
        try:
            pq_score = max(0.0, min(1.0, float(pq_score_raw)))
            doc_ctx.doc_parse_quality_by_id[doc_id_s] = float(pq_score)
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    @staticmethod
    def _document_ready(
        *,
        status: Any,
        doc_meta: dict[str, Any],
        archived_at: Any,
        disabled_at: Any,
        publication_status: Any,
    ) -> bool:
        ready = (
            bool(doc_meta.get("active_pipeline_ready"))
            if "active_pipeline_ready" in doc_meta
            else (str(status or "").lower() == "completed")
        )
        if archived_at is not None or disabled_at is not None:
            ready = False
        if str(publication_status or "published").strip().lower() != "published":
            ready = False
        return bool(ready)

    def _document_active_pipeline_key(self, *, doc_meta: dict[str, Any], document_id: str) -> str | None:
        active_key = str(doc_meta.get("active_doc_pipeline_key") or "").strip()
        if active_key:
            return active_key
        active_hash = str(doc_meta.get("active_pipeline_hash") or doc_meta.get("pipeline_hash") or "").strip()
        if active_hash:
            return f"{document_id}:{active_hash}"
        return None

    def _query_first_chunk_content(
        self,
        db: Session,
        *,
        doc_ids: set[UUID],
        tenant_filter: UUID | None,
    ) -> dict[str, str]:
        first_chunk_by_doc_id: dict[str, str] = {}
        try:
            q = db.query(DocumentChunk.document_id, DocumentChunk.content).filter(
                DocumentChunk.document_id.in_(sorted(doc_ids)),
                DocumentChunk.chunk_index == 0,
            )
            if tenant_filter:
                q = q.filter(DocumentChunk.tenant_id == tenant_filter)
            for doc_id, content in q.all():
                first_chunk_by_doc_id[str(doc_id)] = str(content or "")
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        return first_chunk_by_doc_id

    def _populate_document_titles(
        self,
        doc_ctx: _DocumentEnrichmentContext,
        *,
        doc_ids: set[UUID],
        first_chunk_by_doc_id: dict[str, str],
    ) -> None:
        for doc_id in doc_ids:
            doc_id_s = str(doc_id)
            title = derive_document_title(
                filename=doc_ctx.doc_filename_by_id.get(doc_id_s),
                doc_metadata=doc_ctx.doc_metadata_by_id.get(doc_id_s),
                first_chunk_content=first_chunk_by_doc_id.get(doc_id_s),
            )
            if title:
                doc_ctx.doc_title_by_id[doc_id_s] = title

    def _resolve_allowed_docs_for_enrichment(
        self,
        db: Session,
        *,
        tenant_filter: UUID | None,
        account_id: str | None,
        dataset_filters: set[str],
        doc_ctx: _DocumentEnrichmentContext,
    ) -> set[str] | None:
        if tenant_filter and account_id:
            return self._allowed_docs_for_account(
                db,
                tenant_filter=tenant_filter,
                account_id=account_id,
                dataset_filters=dataset_filters,
                doc_ctx=doc_ctx,
            )
        if account_id and not tenant_filter:
            return set()
        return None

    def _allowed_docs_for_account(
        self,
        db: Session,
        *,
        tenant_filter: UUID,
        account_id: str,
        dataset_filters: set[str],
        doc_ctx: _DocumentEnrichmentContext,
    ) -> set[str]:
        try:
            from app.services.document_access import get_allowed_document_id_sets

            candidate_doc_ids = self._allowed_doc_candidates(dataset_filters=dataset_filters, doc_ctx=doc_ctx)
            if not candidate_doc_ids:
                return set()
            allowed_ids, _missing = get_allowed_document_id_sets(
                db,
                tenant_filter,
                account_id,
                list(candidate_doc_ids),
                check_member=True,
            )
            return {str(doc_id) for doc_id in allowed_ids}
        except Exception as exc:
            _log_retriever_fallback("_enrich_results_with_db_metadata", exc)
            return set()

    def _allowed_doc_candidates(
        self,
        *,
        dataset_filters: set[str],
        doc_ctx: _DocumentEnrichmentContext,
    ) -> set[UUID]:
        candidate_doc_ids = self._ready_candidate_doc_ids(doc_ctx.doc_ready_by_id)
        if dataset_filters and doc_ctx.doc_dataset_by_id:
            candidate_doc_ids = {
                doc_id for doc_id in candidate_doc_ids if doc_ctx.doc_dataset_by_id.get(str(doc_id)) in dataset_filters
            }
        return candidate_doc_ids

    def _ready_candidate_doc_ids(self, doc_ready_by_id: dict[str, bool]) -> set[UUID]:
        candidate_doc_ids: set[UUID] = set()
        for doc_id, ready in doc_ready_by_id.items():
            if not ready:
                continue
            try:
                candidate_doc_ids.add(UUID(str(doc_id)))
            except Exception as exc:
                _log_retriever_fallback("_enrich_results_with_db_metadata", exc)
        return candidate_doc_ids

    def _resolve_enriched_results(
        self,
        results: list[dict[str, Any]],
        *,
        chunks_by_id: dict[str, DocumentChunk],
        chunks_by_pair: dict[tuple[str, int], DocumentChunk],
        doc_ctx: _DocumentEnrichmentContext,
        allowed_docs_str: set[str] | None,
        dataset_filters: set[str],
        embedding_space: str,
        stats0: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for result in results:
            enriched = self._enrich_single_result(
                result,
                chunks_by_id=chunks_by_id,
                chunks_by_pair=chunks_by_pair,
                doc_ctx=doc_ctx,
                allowed_docs_str=allowed_docs_str,
                dataset_filters=dataset_filters,
                embedding_space=embedding_space,
                stats0=stats0,
            )
            if enriched is not None:
                resolved.append(enriched)
        return resolved

    def _enrich_single_result(
        self,
        result: dict[str, Any],
        *,
        chunks_by_id: dict[str, DocumentChunk],
        chunks_by_pair: dict[tuple[str, int], DocumentChunk],
        doc_ctx: _DocumentEnrichmentContext,
        allowed_docs_str: set[str] | None,
        dataset_filters: set[str],
        embedding_space: str,
        stats0: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        meta = dict(result.get("metadata") or {})
        chunk = self._resolve_result_chunk(result, meta, chunks_by_id=chunks_by_id, chunks_by_pair=chunks_by_pair)
        if chunk is None and self.tenant_id:
            self._increment_enrichment_stat(stats0, "filtered_orphaned")
            return None
        if chunk is None:
            result["metadata"] = meta
            return result
        if not self._result_passes_enrichment_guards(
            chunk,
            meta,
            doc_ctx=doc_ctx,
            allowed_docs_str=allowed_docs_str,
            dataset_filters=dataset_filters,
            embedding_space=embedding_space,
            stats0=stats0,
        ):
            return None
        self._merge_chunk_into_result(result, meta, chunk, doc_ctx=doc_ctx)
        result["metadata"] = meta
        return result

    def _resolve_result_chunk(
        self,
        result: dict[str, Any],
        meta: dict[str, Any],
        *,
        chunks_by_id: dict[str, DocumentChunk],
        chunks_by_pair: dict[tuple[str, int], DocumentChunk],
    ) -> DocumentChunk | None:
        cid = result.get("chunk_id") or meta.get("chunk_id")
        chunk = chunks_by_id.get(str(cid)) if cid else None
        if chunk is not None:
            return chunk
        doc_id = meta.get("document_id")
        chunk_index = meta.get("chunk_index")
        try:
            if doc_id is not None and chunk_index is not None:
                return chunks_by_pair.get((str(UUID(str(doc_id))), int(chunk_index)))
        except (TypeError, ValueError, AttributeError):
            return None
        return None

    def _result_passes_enrichment_guards(
        self,
        chunk: DocumentChunk,
        meta: dict[str, Any],
        *,
        doc_ctx: _DocumentEnrichmentContext,
        allowed_docs_str: set[str] | None,
        dataset_filters: set[str],
        embedding_space: str,
        stats0: dict[str, Any] | None,
    ) -> bool:
        doc_id_str = str(chunk.document_id)
        if allowed_docs_str is not None and doc_id_str not in allowed_docs_str:
            self._increment_enrichment_stat(stats0, "filtered_acl")
            return False
        if dataset_filters and doc_ctx.doc_dataset_by_id.get(doc_id_str) not in dataset_filters:
            self._increment_enrichment_stat(stats0, "filtered_dataset")
            return False
        if getattr(chunk, "disabled_at", None) is not None:
            self._increment_enrichment_stat(stats0, "filtered_not_ready")
            return False
        if doc_ctx.doc_ready_by_id and not doc_ctx.doc_ready_by_id.get(doc_id_str, False):
            self._increment_enrichment_stat(stats0, "filtered_not_ready")
            return False
        if not self._embedding_space_allowed(meta, embedding_space=embedding_space):
            self._increment_enrichment_stat(stats0, "filtered_embedding_space")
            return False
        if not self._active_pipeline_allowed(chunk, meta, doc_ctx=doc_ctx):
            self._increment_enrichment_stat(stats0, "filtered_pipeline_version")
            return False
        return True

    @staticmethod
    def _increment_enrichment_stat(stats0: dict[str, Any] | None, key: str) -> None:
        if stats0 is not None:
            stats0[key] = int(stats0.get(key, 0) or 0) + 1

    def _embedding_space_allowed(self, meta: dict[str, Any], *, embedding_space: str) -> bool:
        expected_embedding_space = str(
            meta.get(_RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY) or embedding_space or ""
        ).strip()
        if meta.get(_RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY) is None and meta.get("score") is None:
            return True
        ck_space = str(meta.get("embedding_space_hash") or "").strip()
        return not expected_embedding_space or ck_space == expected_embedding_space

    def _active_pipeline_allowed(
        self,
        chunk: DocumentChunk,
        meta: dict[str, Any],
        *,
        doc_ctx: _DocumentEnrichmentContext,
    ) -> bool:
        active_key = doc_ctx.doc_active_pipeline_key_by_id.get(str(chunk.document_id))
        if not active_key:
            return True
        chunk_key = self._doc_pipeline_key(meta, document_id=str(chunk.document_id))
        return bool(chunk_key and chunk_key == active_key)

    def _merge_chunk_into_result(
        self,
        result: dict[str, Any],
        meta: dict[str, Any],
        chunk: DocumentChunk,
        *,
        doc_ctx: _DocumentEnrichmentContext,
    ) -> None:
        cid_str = str(chunk.id)
        result["chunk_id"] = cid_str
        meta["chunk_id"] = cid_str
        db_content = chunk.content or ""
        if isinstance(db_content, str) and db_content and result.get("content") != db_content:
            result["content"] = db_content
        stored_meta = dict(chunk.doc_metadata or {})
        for key, value in stored_meta.items():
            if key not in meta or meta.get(key) in (None, "", [], {}):
                meta[key] = value
        self._merge_document_labels(meta, chunk, stored_meta=stored_meta, doc_ctx=doc_ctx)
        self._merge_chunk_positions(meta, chunk)
        self._merge_governance_metadata(meta, chunk, doc_ctx=doc_ctx)
        self._merge_document_user_metadata(meta, chunk, doc_ctx=doc_ctx)

    def _merge_document_labels(
        self,
        meta: dict[str, Any],
        chunk: DocumentChunk,
        *,
        stored_meta: dict[str, Any],
        doc_ctx: _DocumentEnrichmentContext,
    ) -> None:
        for key in ("embedding_space_hash", "img_id", "source", "parser_backend", "doc_type_kwd"):
            if stored_meta.get(key) and not meta.get(key):
                meta[key] = stored_meta.get(key)
        doc_id_str = str(chunk.document_id)
        doc_filename = doc_ctx.doc_filename_by_id.get(doc_id_str)
        if doc_filename and (
            not meta.get("filename") or should_replace_source_label(meta.get("filename"), document_id=doc_id_str)
        ):
            meta["filename"] = doc_filename
        if doc_filename and should_replace_source_label(meta.get("source"), document_id=doc_id_str):
            meta["source"] = doc_filename
        doc_title = doc_ctx.doc_title_by_id.get(doc_id_str)
        if doc_title and not meta.get("document_title"):
            meta["document_title"] = doc_title
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

    @staticmethod
    def _merge_chunk_positions(meta: dict[str, Any], chunk: DocumentChunk) -> None:
        if chunk.page_number is not None and not meta.get("page"):
            meta["page"] = chunk.page_number
        if chunk.page_number is not None and not meta.get("page_number"):
            meta["page_number"] = chunk.page_number
        if chunk.start_char is not None and meta.get("start_char") is None:
            meta["start_char"] = int(chunk.start_char)
        if chunk.end_char is not None and meta.get("end_char") is None:
            meta["end_char"] = int(chunk.end_char)
        if meta.get("chunk_index") is None:
            try:
                meta["chunk_index"] = int(getattr(chunk, "chunk_index", None))
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    @staticmethod
    def _merge_governance_metadata(
        meta: dict[str, Any],
        chunk: DocumentChunk,
        *,
        doc_ctx: _DocumentEnrichmentContext,
    ) -> None:
        doc_id_str = str(chunk.document_id)
        if doc_id_str in doc_ctx.doc_authority_by_id:
            meta["_governance_authority_level"] = doc_ctx.doc_authority_by_id[doc_id_str]
        if doc_id_str in doc_ctx.doc_updated_ts_by_id:
            meta["_governance_updated_ts"] = doc_ctx.doc_updated_ts_by_id[doc_id_str]
        if doc_id_str in doc_ctx.doc_publication_by_id:
            meta["_governance_publication_status"] = doc_ctx.doc_publication_by_id[doc_id_str]
        if doc_id_str in doc_ctx.doc_supersedes_by_id:
            meta["_governance_supersedes_document_id"] = doc_ctx.doc_supersedes_by_id[doc_id_str]

    @staticmethod
    def _merge_document_user_metadata(
        meta: dict[str, Any],
        chunk: DocumentChunk,
        *,
        doc_ctx: _DocumentEnrichmentContext,
    ) -> None:
        doc_user = doc_ctx.doc_user_by_id.get(str(chunk.document_id))
        if doc_user and not meta.get("document_user"):
            meta["document_user"] = doc_user
        if meta.get("doc_parse_quality_score") is None:
            pq_score = doc_ctx.doc_parse_quality_by_id.get(str(chunk.document_id))
            if pq_score is not None:
                meta["doc_parse_quality_score"] = float(pq_score)

    def _apply_enrichment_metadata_filter(
        self,
        resolved: list[dict[str, Any]],
        *,
        metadata_filter_override: dict[str, Any] | None,
        stats0: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        effective_metadata_filter = (
            metadata_filter_override if metadata_filter_override is not None else self.metadata_filter
        )
        if not (effective_metadata_filter and self.metadata_filter_enabled):
            return resolved
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
            return resolved
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
            if stats0 is not None:
                stats0["exception"] = str(exc)[:200]
                stats0["output_results"] = 0
            return []

    def _expand_results_with_neighbors(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Optionally attach adjacent chunks around top hits for better continuity."""
        if not results:
            return results

        neighbor_config = self._neighbor_expansion_config()
        window = neighbor_config["window"]
        sibling_enabled = bool(neighbor_config["sibling_enabled"])
        short_doc_max_chunks = int(neighbor_config["short_doc_max_chunks"])
        if window <= 0 and not (sibling_enabled and short_doc_max_chunks > 0):
            return results

        max_added = int(neighbor_config["max_added"])
        sibling_max_added = max(
            0,
            int(settings.RAG_CONTEXT_SIBLING_MAX_ADDED),
        )
        tenant_filter = self.tenant_id

        # Version-aware neighbor fetch:
        # - Some installations keep multiple pipeline versions in `document_chunks`.
        # - We must avoid pulling neighbors from an inactive pipeline version, even for the same document.
        desired_pipeline_by_doc, anchors = self._neighbor_anchor_state(results)

        document_chunks_by_doc: dict[str, list[DocumentChunk]] = {}
        short_doc_ids: set[str] = set()
        doc_ids_for_sibling = {doc_uuid for _, doc_uuid, _, _ in anchors if doc_uuid is not None}

        needed_pairs = self._neighbor_needed_pairs(anchors, window=window, short_doc_ids=short_doc_ids)

        if not needed_pairs:
            return results

        neighbors_by_pair: dict[tuple[str, int], DocumentChunk] = {}
        try:
            document_chunks_by_doc, short_doc_ids, neighbors_by_pair = self._load_neighbor_chunks(
                desired_pipeline_by_doc=desired_pipeline_by_doc,
                doc_ids_for_sibling=doc_ids_for_sibling,
                tenant_filter=tenant_filter,
                sibling_enabled=sibling_enabled,
                short_doc_max_chunks=short_doc_max_chunks,
                needed_pairs=needed_pairs,
            )
        except Exception as exc:
            _log_retriever_fallback("_expand_results_with_neighbors", exc)
            return results

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
                self.context_neighbor_high_threshold if self.context_neighbor_high_threshold is not None else 0.7
            ),
            mid_threshold=float(
                self.context_neighbor_mid_threshold if self.context_neighbor_mid_threshold is not None else 0.4
            ),
            high_span=max(
                0, int(self.context_neighbor_high_span if self.context_neighbor_high_span is not None else window)
            ),
            mid_span=max(0, int(self.context_neighbor_mid_span if self.context_neighbor_mid_span is not None else 1)),
        )
        return expanded

    def _neighbor_expansion_config(self) -> dict[str, int | bool]:
        window_raw = (
            self.context_neighbor_window
            if self.context_neighbor_window is not None
            else getattr(settings, "RAG_CONTEXT_NEIGHBOR_WINDOW", 0)
        )
        max_added_raw = (
            self.context_neighbor_max_added
            if self.context_neighbor_max_added is not None
            else getattr(settings, "RAG_CONTEXT_NEIGHBOR_MAX_ADDED", 0)
        )
        return {
            "window": max(0, int(window_raw or 0)),
            "max_added": max(0, int(max_added_raw or 0)),
            "sibling_enabled": bool(getattr(settings, "RAG_CONTEXT_SIBLING_EXPAND_ENABLED", False)),
            "short_doc_max_chunks": max(
                0,
                int(getattr(settings, "RAG_CONTEXT_SIBLING_SHORT_DOC_MAX_CHUNKS", 0) or 0),
            ),
        }

    def _neighbor_anchor_state(
        self,
        results: list[dict[str, Any]],
    ) -> tuple[dict[str, str], list[tuple[dict[str, Any], UUID | None, int | None, str | None]]]:
        desired_pipeline_by_doc: dict[str, str] = {}
        anchors: list[tuple[dict[str, Any], UUID | None, int | None, str | None]] = []
        for result in results:
            meta = result.get("metadata") or {}
            doc_uuid, idx = self._neighbor_anchor_identity(meta)
            pipeline_key = self._doc_pipeline_key(meta, document_id=str(doc_uuid) if doc_uuid else None)
            if doc_uuid is not None and pipeline_key:
                desired_pipeline_by_doc.setdefault(str(doc_uuid), pipeline_key)
            anchors.append((result, doc_uuid, idx, pipeline_key))
        return desired_pipeline_by_doc, anchors

    @staticmethod
    def _neighbor_anchor_identity(meta: dict[str, Any]) -> tuple[UUID | None, int | None]:
        doc_id = meta.get("document_id")
        chunk_index = meta.get("chunk_index")
        try:
            return (
                UUID(str(doc_id)) if doc_id is not None else None,
                int(chunk_index) if chunk_index is not None else None,
            )
        except (TypeError, ValueError, AttributeError):
            return None, None

    @staticmethod
    def _doc_pipeline_key(meta: dict[str, Any], *, document_id: str | None) -> str | None:
        pipeline_key = str(meta.get("doc_pipeline_key") or "").strip()
        if pipeline_key:
            return pipeline_key
        pipeline_hash = str(meta.get("pipeline_hash") or "").strip()
        if pipeline_hash and document_id:
            return f"{document_id}:{pipeline_hash}"
        return None

    @classmethod
    def _neighbor_needed_pairs(
        cls,
        anchors: list[tuple[dict[str, Any], UUID | None, int | None, str | None]],
        *,
        window: int,
        short_doc_ids: set[str],
    ) -> set[tuple[UUID, int]]:
        needed_pairs: set[tuple[UUID, int]] = set()
        for _result, doc_uuid, idx, _pipeline_key in anchors:
            if doc_uuid is None or idx is None or str(doc_uuid) in short_doc_ids:
                continue
            for delta in range(-window, window + 1):
                if delta == 0 or idx + delta < 0:
                    continue
                needed_pairs.add((doc_uuid, idx + delta))
        return needed_pairs

    def _load_neighbor_chunks(
        self,
        *,
        desired_pipeline_by_doc: dict[str, str],
        doc_ids_for_sibling: set[UUID],
        tenant_filter: UUID | None,
        sibling_enabled: bool,
        short_doc_max_chunks: int,
        needed_pairs: set[tuple[UUID, int]],
    ) -> tuple[dict[str, list[DocumentChunk]], set[str], dict[tuple[str, int], DocumentChunk]]:
        document_chunks_by_doc: dict[str, list[DocumentChunk]] = {}
        short_doc_ids: set[str] = set()
        neighbors_by_pair: dict[tuple[str, int], DocumentChunk] = {}
        db = self._open_session()
        try:
            if sibling_enabled and short_doc_max_chunks > 0 and doc_ids_for_sibling:
                document_chunks_by_doc = self._load_document_chunks_for_siblings(
                    db,
                    desired_pipeline_by_doc=desired_pipeline_by_doc,
                    doc_ids_for_sibling=doc_ids_for_sibling,
                    tenant_filter=tenant_filter,
                )
                short_doc_ids = {
                    doc_key
                    for doc_key, rows in document_chunks_by_doc.items()
                    if select_document_expansion_mode(
                        total_chunks=len(rows),
                        short_doc_max_chunks=short_doc_max_chunks,
                    )
                    == "sibling"
                }
            neighbors_by_pair = self._load_neighbor_pairs(
                db,
                desired_pipeline_by_doc=desired_pipeline_by_doc,
                needed_pairs=needed_pairs,
                tenant_filter=tenant_filter,
            )
            return document_chunks_by_doc, short_doc_ids, neighbors_by_pair
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _load_document_chunks_for_siblings(
        self,
        db: Session,
        *,
        desired_pipeline_by_doc: dict[str, str],
        doc_ids_for_sibling: set[UUID],
        tenant_filter: UUID | None,
    ) -> dict[str, list[DocumentChunk]]:
        q_all = db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(list(doc_ids_for_sibling)))
        if tenant_filter:
            q_all = q_all.filter(DocumentChunk.tenant_id == tenant_filter)
        document_chunks_by_doc: dict[str, list[DocumentChunk]] = {}
        for chunk in q_all.all():
            if not self._chunk_matches_desired_pipeline(chunk, desired_pipeline_by_doc):
                continue
            document_chunks_by_doc.setdefault(str(chunk.document_id), []).append(chunk)
        return document_chunks_by_doc

    def _load_neighbor_pairs(
        self,
        db: Session,
        *,
        desired_pipeline_by_doc: dict[str, str],
        needed_pairs: set[tuple[UUID, int]],
        tenant_filter: UUID | None,
    ) -> dict[tuple[str, int], DocumentChunk]:
        q = db.query(DocumentChunk).filter(
            tuple_(DocumentChunk.document_id, DocumentChunk.chunk_index).in_(list(needed_pairs))
        )
        if tenant_filter:
            q = q.filter(DocumentChunk.tenant_id == tenant_filter)
        neighbors_by_pair: dict[tuple[str, int], DocumentChunk] = {}
        for chunk in q.all():
            if not self._chunk_matches_desired_pipeline(chunk, desired_pipeline_by_doc):
                continue
            neighbors_by_pair[(str(chunk.document_id), int(chunk.chunk_index))] = chunk
        return neighbors_by_pair

    def _chunk_matches_desired_pipeline(
        self,
        chunk: DocumentChunk,
        desired_pipeline_by_doc: dict[str, str],
    ) -> bool:
        desired = desired_pipeline_by_doc.get(str(chunk.document_id))
        if not desired:
            return True
        stored_meta = dict(getattr(chunk, "doc_metadata", None) or {})
        ck_key = self._doc_pipeline_key(stored_meta, document_id=str(chunk.document_id))
        return bool(ck_key and ck_key == desired)

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

        mode = self._parent_child_merge_mode()
        min_children = max(1, int(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_MIN_CHILDREN", 2) or 2))
        max_parents = max(0, int(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_MAX_PARENTS", 20) or 20))
        child_groups, parent_results, child_chunk_ids_by_group = self._group_parent_child_results(results)

        if not child_groups:
            return results

        desired_pipeline_by_doc = self._desired_parent_pipeline_by_doc(results)
        selected_keys = self._selected_parent_child_keys(
            child_groups,
            mode=mode,
            min_children=min_children,
            max_parents=max_parents,
        )

        if not selected_keys:
            return results

        fetched_parents = self._fetch_parent_child_chunks(
            selected_keys=selected_keys,
            parent_results=parent_results,
            desired_pipeline_by_doc=desired_pipeline_by_doc,
            tenant_filter=self.tenant_id,
        )
        best_score_by_group = self._best_child_score_by_group(child_groups, selected_keys=selected_keys)

        if mode == "append":
            return self._append_parent_child_results(
                results=results,
                selected_keys=selected_keys,
                parent_results=parent_results,
                fetched_parents=fetched_parents,
                best_score_by_group=best_score_by_group,
            )
        return self._replace_parent_child_results(
            results=results,
            selected_keys=selected_keys,
            child_chunk_ids_by_group=child_chunk_ids_by_group,
            parent_results=parent_results,
            fetched_parents=fetched_parents,
            best_score_by_group=best_score_by_group,
        )

    @staticmethod
    def _parent_child_merge_mode() -> str:
        mode = str(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_MODE", "replace") or "replace").strip().lower()
        return mode if mode in {"replace", "append"} else "replace"

    def _group_parent_child_results(
        self,
        results: list[dict[str, Any]],
    ) -> tuple[
        dict[tuple[str, str], list[dict[str, Any]]],
        dict[tuple[str, str], dict[str, Any]],
        dict[tuple[str, str], set[str]],
    ]:
        child_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        parent_results: dict[tuple[str, str], dict[str, Any]] = {}
        child_chunk_ids_by_group: dict[tuple[str, str], set[str]] = {}
        for result in results:
            meta = result.get("metadata") or {}
            role = str(meta.get("chunk_role") or "").strip().lower()
            doc_id = str(meta.get("document_id") or "").strip()
            family_key = self._resolve_family_collapse_key(meta, result=result)
            if not family_key or not doc_id:
                continue
            key = (doc_id, family_key)
            if role == "parent":
                parent_results[key] = result
                continue
            if role != "child":
                continue
            child_groups.setdefault(key, []).append(result)
            cid = result.get("chunk_id") or meta.get("chunk_id")
            if cid:
                child_chunk_ids_by_group.setdefault(key, set()).add(str(cid))
        return child_groups, parent_results, child_chunk_ids_by_group

    def _desired_parent_pipeline_by_doc(self, results: list[dict[str, Any]]) -> dict[str, str]:
        desired_pipeline_by_doc: dict[str, str] = {}
        for result in results:
            meta = result.get("metadata") or {}
            doc_id = str(meta.get("document_id") or "").strip()
            pipeline_key = self._doc_pipeline_key(meta, document_id=doc_id or None)
            if doc_id and pipeline_key:
                desired_pipeline_by_doc.setdefault(doc_id, pipeline_key)
        return desired_pipeline_by_doc

    def _selected_parent_child_keys(
        self,
        child_groups: dict[tuple[str, str], list[dict[str, Any]]],
        *,
        mode: str,
        min_children: int,
        max_parents: int,
    ) -> list[tuple[str, str]]:
        scored_groups = sorted(
            ((self._best_child_score(items), key) for key, items in child_groups.items()),
            key=lambda item: item[0],
            reverse=True,
        )
        if max_parents and len(scored_groups) > max_parents:
            scored_groups = scored_groups[:max_parents]
        return [
            key
            for _score, key in scored_groups
            if mode != "replace" or len(child_groups.get(key) or []) >= min_children
        ]

    def _best_child_score_by_group(
        self,
        child_groups: dict[tuple[str, str], list[dict[str, Any]]],
        *,
        selected_keys: list[tuple[str, str]],
    ) -> dict[tuple[str, str], float]:
        return {key: self._best_child_score(child_groups.get(key) or []) for key in selected_keys}

    @staticmethod
    def _best_child_score(items: list[dict[str, Any]]) -> float:
        best = 0.0
        for item in items:
            try:
                best = max(best, float(item.get("score", 0.0) or 0.0))
            except (TypeError, ValueError, AttributeError):
                continue
        return best

    def _fetch_parent_child_chunks(
        self,
        *,
        selected_keys: list[tuple[str, str]],
        parent_results: dict[tuple[str, str], dict[str, Any]],
        desired_pipeline_by_doc: dict[str, str],
        tenant_filter: UUID | None,
    ) -> dict[tuple[str, str], DocumentChunk]:
        missing_keys = [key for key in selected_keys if key not in parent_results]
        doc_ids, family_keys = self._parent_child_lookup_scope(missing_keys)
        if not doc_ids or not family_keys:
            return {}
        db = self._open_session()
        try:
            return self._query_parent_child_chunks(
                db,
                doc_ids=doc_ids,
                family_keys=family_keys,
                desired_pipeline_by_doc=desired_pipeline_by_doc,
                tenant_filter=tenant_filter,
            )
        except Exception as exc:
            _log_retriever_fallback("_auto_merge_parent_child", exc)
            return {}
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _parent_child_lookup_scope(
        self,
        missing_keys: list[tuple[str, str]],
    ) -> tuple[set[UUID], set[str]]:
        doc_ids: set[UUID] = set()
        family_keys: set[str] = set()
        for doc_id, family_key in missing_keys:
            try:
                doc_ids.add(UUID(doc_id))
            except Exception as exc:
                _log_retriever_fallback("_auto_merge_parent_child", exc)
                continue
            if family_key:
                family_keys.add(family_key)
        return doc_ids, family_keys

    def _query_parent_child_chunks(
        self,
        db: Session,
        *,
        doc_ids: set[UUID],
        family_keys: set[str],
        desired_pipeline_by_doc: dict[str, str],
        tenant_filter: UUID | None,
    ) -> dict[tuple[str, str], DocumentChunk]:
        q = db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(list(doc_ids)))
        if tenant_filter:
            q = q.filter(DocumentChunk.tenant_id == tenant_filter)
        q = q.filter(DocumentChunk.doc_metadata["chunk_role"].astext == "parent")  # type: ignore[attr-defined]
        q = q.filter(
            or_(
                DocumentChunk.doc_metadata["hierarchy_family_key"].astext.in_(list(family_keys)),  # type: ignore[attr-defined]
                DocumentChunk.doc_metadata["parent_id"].astext.in_(list(family_keys)),  # type: ignore[attr-defined]
            )
        )
        fetched_parents: dict[tuple[str, str], DocumentChunk] = {}
        for chunk in q.all():
            meta = dict(getattr(chunk, "doc_metadata", None) or {})
            family_key = self._resolve_family_collapse_key(meta)
            if not family_key or not self._chunk_matches_desired_pipeline(chunk, desired_pipeline_by_doc):
                continue
            fetched_parents[(str(chunk.document_id), family_key)] = chunk
        return fetched_parents

    def _parent_result_for(
        self,
        key: tuple[str, str],
        *,
        parent_results: dict[tuple[str, str], dict[str, Any]],
        fetched_parents: dict[tuple[str, str], DocumentChunk],
        best_child_score: float,
    ) -> dict[str, Any] | None:
        if key in parent_results:
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
        chunk = fetched_parents.get(key)
        if chunk is None:
            return None
        cid = str(chunk.id)
        stored_meta = dict(chunk.doc_metadata or {})
        stored_meta.setdefault("tenant_id", str(chunk.tenant_id))
        stored_meta.setdefault("document_id", str(chunk.document_id))
        stored_meta.setdefault("chunk_index", int(chunk.chunk_index))
        stored_meta.setdefault("chunk_id", cid)
        if chunk.page_number is not None:
            stored_meta.setdefault("page", chunk.page_number)
        if not stored_meta.get("source"):
            stored_meta["source"] = "unknown"
        stored_meta["retrieval_role"] = "parent"
        return {
            "chunk_id": cid,
            "content": chunk.content,
            "metadata": stored_meta,
            "score": float(best_child_score * 0.97),
        }

    def _append_parent_child_results(
        self,
        *,
        results: list[dict[str, Any]],
        selected_keys: list[tuple[str, str]],
        parent_results: dict[tuple[str, str], dict[str, Any]],
        fetched_parents: dict[tuple[str, str], DocumentChunk],
        best_score_by_group: dict[tuple[str, str], float],
    ) -> list[dict[str, Any]]:
        inserted: set[tuple[str, str]] = set()
        selected = set(selected_keys)
        out: list[dict[str, Any]] = []
        for result in results:
            out.append(result)
            meta = result.get("metadata") or {}
            if str(meta.get("chunk_role") or "").strip().lower() != "child":
                continue
            key = (
                str(meta.get("document_id") or "").strip(),
                self._resolve_family_collapse_key(meta, result=result),
            )
            if key not in selected or key in inserted:
                continue
            inserted.add(key)
            if key in parent_results:
                continue
            parent = self._parent_result_for(
                key,
                parent_results=parent_results,
                fetched_parents=fetched_parents,
                best_child_score=best_score_by_group.get(key, 0.0),
            )
            if parent is not None:
                out.append(parent)
        return out

    def _replace_parent_child_results(
        self,
        *,
        results: list[dict[str, Any]],
        selected_keys: list[tuple[str, str]],
        child_chunk_ids_by_group: dict[tuple[str, str], set[str]],
        parent_results: dict[tuple[str, str], dict[str, Any]],
        fetched_parents: dict[tuple[str, str], DocumentChunk],
        best_score_by_group: dict[tuple[str, str], float],
    ) -> list[dict[str, Any]]:
        selected = set(selected_keys)
        removed_child_ids = {cid for key in selected for cid in child_chunk_ids_by_group.get(key, set())}
        inserted: set[tuple[str, str]] = set()
        out: list[dict[str, Any]] = []
        for result in results:
            meta = result.get("metadata") or {}
            cid = str(result.get("chunk_id") or meta.get("chunk_id") or "")
            if meta.get("retrieval_role") == "neighbor" and str(meta.get("neighbor_of") or "") in removed_child_ids:
                continue
            role = str(meta.get("chunk_role") or "").strip().lower()
            key = (
                str(meta.get("document_id") or "").strip(),
                self._resolve_family_collapse_key(meta, result=result),
            )
            if key in selected and role in {"child", "parent"}:
                if key in inserted:
                    continue
                parent = self._parent_result_for(
                    key,
                    parent_results=parent_results,
                    fetched_parents=fetched_parents,
                    best_child_score=best_score_by_group.get(key, 0.0),
                )
                inserted.add(key)
                if parent is not None:
                    out.append(parent)
                continue
            if cid and cid in removed_child_ids and role == "child":
                continue
            out.append(result)
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
        annotated, annotated_count, promoted_count = self._annotated_metadata_anchor_results(
            query=query,
            results=results,
            phrase_boost_weight=phrase_boost_weight,
        )

        if annotated_count <= 0:
            if stats is not None:
                stats["applied"] = False
                stats["annotated"] = 0
            return results

        before_top = self._result_key(annotated[0][0]) if annotated else ""
        annotated.sort(key=self._metadata_anchor_sort_key_factory(annotated, result_count=len(results)))
        ordered = [item for item, _pos in annotated]
        after_top = self._result_key(ordered[0]) if ordered else ""
        if stats is not None:
            stats["applied"] = True
            stats["annotated"] = int(annotated_count)
            stats["score_promoted"] = int(promoted_count)
            stats["top_changed"] = bool(before_top and after_top and before_top != after_top)
        return ordered

    def _annotated_metadata_anchor_results(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
        phrase_boost_weight: float,
    ) -> tuple[list[tuple[dict[str, Any], int]], int, int]:
        annotated: list[tuple[dict[str, Any], int]] = []
        annotated_count = 0
        promoted_count = 0
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
        return annotated, annotated_count, promoted_count

    def _metadata_anchor_sort_key_factory(
        self,
        annotated: list[tuple[dict[str, Any], int]],
        *,
        result_count: int,
    ):
        has_budgeted_prefix = any(
            isinstance(result, dict) and result.get("fusion_budgeted_prefix_rank") is not None
            for result, _pos in annotated
        )
        best_anchor_score = max(
            _float_or_default(item.get("metadata_exact_match_score"), 0.0) for item, _pos in annotated
        )

        def sort_key(pair: tuple[dict[str, Any], int]) -> tuple[float, float, int]:
            item, pos = pair
            if has_budgeted_prefix:
                try:
                    prefix_rank = int(item.get("fusion_budgeted_prefix_rank"))
                except (TypeError, ValueError):
                    prefix_rank = result_count + int(pos) + 1
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

        return sort_key
