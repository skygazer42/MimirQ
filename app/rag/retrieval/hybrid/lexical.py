"""Lexical DB search and metadata exact-anchor DB fallback for the hybrid retriever.

Split out of ``app.rag.retriever`` (see ``app.rag.retrieval.hybrid``). The
methods below run on the ``HybridRetriever`` instance via mixin inheritance;
sessions are opened via ``self._open_session()`` so monkeypatches on
``app.rag.retriever.SessionLocal`` keep working.
"""

import re
import unicodedata
from typing import Any
from uuid import UUID

from sqlalchemy import Text as SQLText
from sqlalchemy import case, func, or_, text
from sqlalchemy import cast as sql_cast
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.preprocessing.tokenization import tokenize_for_bm25
from app.rag.retrieval.hybrid.common import (
    NON_CRITICAL_RETRIEVER_FALLBACK_LOG,
    _log_retriever_fallback,
    _metadata_exact_anchor_match,
    _query_looks_like_cjk_metadata_anchor,
    logger,
)


class LexicalDBMixin:
    """Postgres-backed lexical retrieval (FTS/trigram/CJK-token) and metadata exact-anchor fallback."""

    @staticmethod
    def _coerce_dataset_scope_values(raw: Any) -> list[UUID]:
        values: list[Any]
        if isinstance(raw, dict):
            if "$eq" in raw:
                values = [raw.get("$eq")]
            elif "$in" in raw and isinstance(raw.get("$in"), list | tuple | set):
                values = list(raw.get("$in") or [])
            else:
                values = []
        elif isinstance(raw, list | tuple | set):
            values = list(raw)
        else:
            values = [raw]

        dataset_uuids: list[UUID] = []
        seen: set[str] = set()
        for item in values:
            text = str(item or "").strip()
            if not text:
                continue
            try:
                dataset_uuid = UUID(text)
            except (TypeError, ValueError, AttributeError):
                continue
            key = str(dataset_uuid)
            if key in seen:
                continue
            seen.add(key)
            dataset_uuids.append(dataset_uuid)
        return dataset_uuids

    @classmethod
    def _collect_lexical_dataset_scope(cls, metadata_filter: dict[str, Any] | None) -> list[UUID]:
        if not isinstance(metadata_filter, dict) or not metadata_filter:
            return []

        direct = cls._coerce_dataset_scope_values(metadata_filter.get("dataset_id"))
        if direct:
            return direct

        and_parts = metadata_filter.get("$and")
        if isinstance(and_parts, list):
            scoped: list[UUID] = []
            seen: set[str] = set()
            for part in and_parts:
                if not isinstance(part, dict):
                    continue
                for dataset_uuid in cls._collect_lexical_dataset_scope(part):
                    key = str(dataset_uuid)
                    if key in seen:
                        continue
                    seen.add(key)
                    scoped.append(dataset_uuid)
            if scoped:
                return scoped

        or_parts = metadata_filter.get("$or")
        if isinstance(or_parts, list) and or_parts:
            scoped_parts: list[list[UUID]] = []
            for part in or_parts:
                if not isinstance(part, dict):
                    return []
                part_scope = cls._collect_lexical_dataset_scope(part)
                if not part_scope:
                    return []
                scoped_parts.append(part_scope)
            scoped: list[UUID] = []
            seen: set[str] = set()
            for part_scope in scoped_parts:
                for dataset_uuid in part_scope:
                    key = str(dataset_uuid)
                    if key in seen:
                        continue
                    seen.add(key)
                    scoped.append(dataset_uuid)
            return scoped

        return []

    @classmethod
    def _lexical_dataset_scope(cls, metadata_filter: dict[str, Any] | None) -> tuple[list[UUID] | None, str | None]:
        dataset_uuids = cls._collect_lexical_dataset_scope(metadata_filter)
        dataset_str = str(dataset_uuids[0]) if dataset_uuids else None
        return (dataset_uuids or None), dataset_str

    @staticmethod
    def _lexical_search_config(top_k: int) -> tuple[str, int, bool, int]:
        fts_config = str(getattr(settings, "LEXICAL_DB_FTS_CONFIG", "simple") or "simple").strip() or "simple"
        fetch_mult = max(1, int(getattr(settings, "LEXICAL_DB_FETCH_MULTIPLIER", 4) or 4))
        fetch_cap = max(10, int(getattr(settings, "LEXICAL_DB_MAX_CANDIDATES", 200) or 200))
        limit = max(0, int(top_k or 0))
        fetch_k = min(fetch_cap, max(limit, limit * fetch_mult))
        want_trgm = bool(getattr(settings, "LEXICAL_DB_TRGM_ENABLED", True))
        trgm_min_chars = max(1, int(getattr(settings, "LEXICAL_DB_TRGM_MIN_QUERY_CHARS", 3) or 3))
        return fts_config, fetch_k, want_trgm, trgm_min_chars

    @staticmethod
    def _lexical_cjk_token_terms(raw_query: str) -> list[str]:
        text = str(raw_query or "").strip()
        if not text or not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text):
            return []
        try:
            max_terms = max(1, min(16, int(getattr(settings, "LEXICAL_DB_CJK_TOKEN_MAX_TERMS", 6) or 6)))
        except (TypeError, ValueError):
            max_terms = 6

        candidates: list[str] = []
        seen: set[str] = set()
        for token in tokenize_for_bm25(text):
            term = str(token or "").strip()
            if len(term) < 2:
                continue
            # This channel is for CJK queries, but ASCII/numeric tokens inside
            # the same query (codes, years, IDs) are useful exact constraints.
            if not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff0-9A-Za-z]", term):
                continue
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(term)

        selected: list[str] = []
        for term in sorted(candidates, key=lambda item: (-len(item), candidates.index(item))):
            folded = term.casefold()
            if any(folded in existing.casefold() for existing in selected):
                continue
            selected.append(term)
            if len(selected) >= max_terms:
                break
        return selected

    @staticmethod
    def _lexical_base_query(
        db: Session,
        *,
        tenant_uuid: UUID,
        dataset_uuid: UUID | list[UUID] | None,
        document_ids: list[UUID] | None,
    ) -> Any:
        query = (
            db.query(
                DocumentChunk.id,
                DocumentChunk.content,
                DocumentChunk.doc_metadata,
                DocumentChunk.tenant_id,
                DocumentChunk.document_id,
                DocumentChunk.chunk_index,
                DocumentChunk.page_number,
            )
            .join(DBDocument, DocumentChunk.document_id == DBDocument.id)
            .filter(DBDocument.status == "completed")
            .filter(DBDocument.publication_status == "published")
            .filter(DBDocument.archived_at.is_(None))
            .filter(DBDocument.disabled_at.is_(None))
            .filter(DocumentChunk.disabled_at.is_(None))
            .filter(DocumentChunk.tenant_id == tenant_uuid)
        )
        if isinstance(dataset_uuid, list):
            if len(dataset_uuid) == 1:
                query = query.filter(DBDocument.dataset_id == dataset_uuid[0])
            elif dataset_uuid:
                query = query.filter(DBDocument.dataset_id.in_(dataset_uuid))
        elif dataset_uuid is not None:
            query = query.filter(DBDocument.dataset_id == dataset_uuid)
        if document_ids:
            query = query.filter(DocumentChunk.document_id.in_(document_ids))
        return query

    def _lexical_result_from_row(
        self,
        row: Any,
        *,
        method: str,
        dataset_str: str | None,
        metadata_filter: dict[str, Any] | None,
    ) -> tuple[str, dict[str, Any]] | None:
        try:
            values = tuple(row)
            if len(values) == 9:
                (
                    chunk_id,
                    content,
                    doc_metadata,
                    tenant_uuid_row,
                    document_uuid_row,
                    chunk_index,
                    page_number,
                    dataset_uuid_row,
                    score_raw,
                ) = values
            else:
                (
                    chunk_id,
                    content,
                    doc_metadata,
                    tenant_uuid_row,
                    document_uuid_row,
                    chunk_index,
                    page_number,
                    score_raw,
                ) = values
                dataset_uuid_row = None
        except (TypeError, ValueError, AttributeError):
            return None

        cid = str(chunk_id)
        score = float(score_raw or 0.0)
        meta = dict(doc_metadata or {})
        meta.setdefault("tenant_id", str(tenant_uuid_row))
        meta.setdefault("document_id", str(document_uuid_row))
        meta.setdefault("chunk_index", int(chunk_index) if chunk_index is not None else None)
        meta.setdefault("chunk_id", cid)
        meta.setdefault("source", meta.get("source", "unknown"))
        effective_dataset_str = str(dataset_uuid_row) if dataset_uuid_row is not None else dataset_str
        if effective_dataset_str:
            meta.setdefault("dataset_id", effective_dataset_str)
        if page_number is not None and not meta.get("page"):
            meta["page"] = page_number
        meta.setdefault("lexical_method", method)
        meta.setdefault("lexical_score_raw", score)
        if metadata_filter and not self._match_metadata_filter(meta, metadata_filter):
            return None
        return cid, {"chunk_id": cid, "content": content or "", "metadata": meta, "score": score}

    def _add_lexical_rows(
        self,
        *,
        rows: Any,
        results_by_id: dict[str, dict[str, Any]],
        method: str,
        dataset_str: str | None,
        metadata_filter: dict[str, Any] | None,
        replace_if_higher: bool = False,
    ) -> None:
        for row in rows:
            parsed = self._lexical_result_from_row(
                row,
                method=method,
                dataset_str=dataset_str,
                metadata_filter=metadata_filter,
            )
            if parsed is None:
                continue
            cid, result = parsed
            existing = results_by_id.get(cid)
            if not replace_if_higher or existing is None or float(existing.get("score", 0.0) or 0.0) < float(
                result.get("score", 0.0) or 0.0
            ):
                results_by_id[cid] = result

    def _collect_lexical_fts_results(
        self,
        *,
        db: Session,
        tenant_uuid: UUID,
        dataset_uuid: UUID | list[UUID] | None,
        document_ids: list[UUID] | None,
        fts_config: str,
        raw_query: str,
        fetch_k: int,
        method: str,
        tsquery_builder: Any,
        dataset_str: str | None,
        metadata_filter: dict[str, Any] | None,
        results_by_id: dict[str, dict[str, Any]],
    ) -> None:
        try:
            vector = func.to_tsvector(fts_config, DocumentChunk.content)
            tsq = tsquery_builder(fts_config, raw_query)
            rank = func.ts_rank_cd(vector, tsq).label("fts_rank")
            rows = (
                self._lexical_base_query(
                    db,
                    tenant_uuid=tenant_uuid,
                    dataset_uuid=dataset_uuid,
                    document_ids=document_ids,
                )
                .add_columns(rank)
                .filter(vector.op("@@")(tsq))
                .order_by(rank.desc())
                .limit(fetch_k)
                .all()
            )
            self._add_lexical_rows(
                rows=rows,
                results_by_id=results_by_id,
                method=method,
                dataset_str=dataset_str,
                metadata_filter=metadata_filter,
            )
        except Exception as exc:
            logger.debug("Lexical %s query failed: %s", method, exc)

    def _lexical_pg_trgm_available_now(self, db: Session) -> bool:
        pg_trgm_available = self._lexical_pg_trgm_available
        if pg_trgm_available is not None:
            return bool(pg_trgm_available)
        try:
            row = db.execute(text("SELECT 1 FROM pg_extension WHERE extname='pg_trgm' LIMIT 1;")).first()
            pg_trgm_available = bool(row)
        except Exception as exc:
            _log_retriever_fallback('_search_lexical_db', exc)
            pg_trgm_available = False
        self._lexical_pg_trgm_available = pg_trgm_available
        return bool(pg_trgm_available)

    def _collect_lexical_trigram_results(
        self,
        *,
        db: Session,
        tenant_uuid: UUID,
        dataset_uuid: UUID | list[UUID] | None,
        document_ids: list[UUID] | None,
        raw_query: str,
        fetch_k: int,
        dataset_str: str | None,
        metadata_filter: dict[str, Any] | None,
        results_by_id: dict[str, dict[str, Any]],
    ) -> None:
        try:
            sim = func.similarity(DocumentChunk.content, raw_query).label("trgm_sim")
            rows = (
                self._lexical_base_query(
                    db,
                    tenant_uuid=tenant_uuid,
                    dataset_uuid=dataset_uuid,
                    document_ids=document_ids,
                )
                .add_columns(sim)
                .filter(DocumentChunk.content.op("%")(raw_query))
                .order_by(sim.desc())
                .limit(fetch_k)
                .all()
            )
            self._add_lexical_rows(
                rows=rows,
                results_by_id=results_by_id,
                method="trgm",
                dataset_str=dataset_str,
                metadata_filter=metadata_filter,
                replace_if_higher=True,
            )
        except Exception as exc:
            logger.debug("Lexical trigram query failed: %s", exc)

    def _collect_lexical_cjk_token_results(
        self,
        *,
        db: Session,
        tenant_uuid: UUID,
        dataset_uuid: UUID | list[UUID] | None,
        document_ids: list[UUID] | None,
        raw_query: str,
        fetch_k: int,
        dataset_str: str | None,
        metadata_filter: dict[str, Any] | None,
        results_by_id: dict[str, dict[str, Any]],
    ) -> None:
        if not bool(getattr(settings, "LEXICAL_DB_CJK_TOKEN_CONTAINMENT_ENABLED", True)):
            return
        terms = self._lexical_cjk_token_terms(raw_query)
        if not terms:
            return

        conditions = []
        score_expr = None
        hit_expr = None
        for term in terms:
            pattern = f"%{self._escape_sql_like_term(term)}%"
            condition = DocumentChunk.content.ilike(pattern, escape="\\")
            conditions.append(condition)
            score_piece = case((condition, float(len(term))), else_=0.0)
            hit_piece = case((condition, 1), else_=0)
            score_expr = score_piece if score_expr is None else score_expr + score_piece
            hit_expr = hit_piece if hit_expr is None else hit_expr + hit_piece
        if not conditions or score_expr is None or hit_expr is None:
            return

        try:
            configured_min_hits = int(getattr(settings, "LEXICAL_DB_CJK_TOKEN_MIN_HITS", 0) or 0)
        except (TypeError, ValueError):
            configured_min_hits = 0
        min_hits = configured_min_hits
        if min_hits <= 0:
            min_hits = min(3, max(1, len(terms) // 2))

        try:
            rows = (
                self._lexical_base_query(
                    db,
                    tenant_uuid=tenant_uuid,
                    dataset_uuid=dataset_uuid,
                    document_ids=document_ids,
                )
                .add_columns(score_expr.label("cjk_token_score"))
                .filter(or_(*conditions))
                .filter(hit_expr >= min_hits)
                .order_by(score_expr.desc(), DocumentChunk.chunk_index.asc())
                .limit(fetch_k)
                .all()
            )
            self._add_lexical_rows(
                rows=rows,
                results_by_id=results_by_id,
                method="cjk_token",
                dataset_str=dataset_str,
                metadata_filter=metadata_filter,
                replace_if_higher=True,
            )
        except Exception as exc:
            logger.debug("Lexical CJK token query failed: %s", exc)

    def _search_lexical_db_with_session(
        self,
        *,
        db: Session,
        raw_query: str,
        top_k: int,
        tenant_uuid: UUID,
        document_ids: list[UUID] | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        dataset_uuid, dataset_str = self._lexical_dataset_scope(metadata_filter)
        fts_config, fetch_k, want_trgm, trgm_min_chars = self._lexical_search_config(top_k)
        limit = max(0, int(top_k or 0))
        if limit <= 0:
            return []

        bind = db.get_bind()
        if not bind or getattr(getattr(bind, "dialect", None), "name", "") != "postgresql":
            return []

        results_by_id: dict[str, dict[str, Any]] = {}
        self._collect_lexical_fts_results(
            db=db,
            tenant_uuid=tenant_uuid,
            dataset_uuid=dataset_uuid,
            document_ids=document_ids,
            fts_config=fts_config,
            raw_query=raw_query,
            fetch_k=fetch_k,
            method="fts",
            tsquery_builder=func.websearch_to_tsquery,
            dataset_str=dataset_str,
            metadata_filter=metadata_filter,
            results_by_id=results_by_id,
        )

        if not results_by_id:
            self._collect_lexical_fts_results(
                db=db,
                tenant_uuid=tenant_uuid,
                dataset_uuid=dataset_uuid,
                document_ids=document_ids,
                fts_config=fts_config,
                raw_query=raw_query,
                fetch_k=fetch_k,
                method="fts_plain",
                tsquery_builder=func.plainto_tsquery,
                dataset_str=dataset_str,
                metadata_filter=metadata_filter,
                results_by_id=results_by_id,
            )

        if want_trgm and len(raw_query) >= trgm_min_chars and self._lexical_pg_trgm_available_now(db):
            self._collect_lexical_trigram_results(
                db=db,
                tenant_uuid=tenant_uuid,
                dataset_uuid=dataset_uuid,
                document_ids=document_ids,
                raw_query=raw_query,
                fetch_k=fetch_k,
                dataset_str=dataset_str,
                metadata_filter=metadata_filter,
                results_by_id=results_by_id,
            )

        self._collect_lexical_cjk_token_results(
            db=db,
            tenant_uuid=tenant_uuid,
            dataset_uuid=dataset_uuid,
            document_ids=document_ids,
            raw_query=raw_query,
            fetch_k=fetch_k,
            dataset_str=dataset_str,
            metadata_filter=metadata_filter,
            results_by_id=results_by_id,
        )

        if not results_by_id:
            return []
        merged = list(results_by_id.values())
        merged.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
        return merged[:limit]

    def _search_lexical_db(  # noqa: PLR0915
        self,
        *,
        query: str,
        top_k: int = 10,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Persistent lexical retrieval backed by the primary Postgres DB.

        Intended as a "last mile" safety net for false negatives (numbers, codes, exact phrases)
        when dense retrieval or in-memory BM25 miss.

        Implementation:
        - Full-text search: websearch_to_tsquery + ts_rank_cd (fast with a GIN tsvector index)
        - Optional: pg_trgm similarity fallback for short / code-like queries (fast with a trigram index)

        Returns dicts with raw `score` values; downstream fusion normalizes.
        """
        raw_query = str(query or "").strip()
        if not raw_query:
            return []
        if not bool(getattr(settings, "LEXICAL_DB_ENABLED", True)):
            return []

        tenant_uuid = self._resolve_tenant_uuid(tenant_id)
        if tenant_uuid is None:
            return []

        db = self._open_session()
        try:
            return self._search_lexical_db_with_session(
                db=db,
                raw_query=raw_query,
                top_k=top_k,
                tenant_uuid=tenant_uuid,
                document_ids=document_ids,
                metadata_filter=metadata_filter,
            )
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    @staticmethod
    def _escape_sql_like_term(value: str) -> str:
        return str(value or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def _metadata_exact_db_like_terms(value: str) -> list[str]:
        raw = str(value or "").strip()
        if not raw:
            return []
        variants: list[str] = []
        seen: set[str] = set()

        def add(text: str) -> None:
            item = str(text or "").strip()
            if not item or item in seen:
                return
            seen.add(item)
            variants.append(item)

        add(raw)
        try:
            add(unicodedata.normalize("NFKC", raw))
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        for item in list(variants):
            add(item.translate(str.maketrans({"(": "（", ")": "）"})))
            add(item.translate(str.maketrans({"（": "(", "）": ")"})))
        return variants

    def _metadata_exact_result_from_row(
        self,
        row: Any,
        *,
        query: str,
        dataset_str: str | None,
        metadata_filter: dict[str, Any] | None,
    ) -> tuple[str, dict[str, Any]] | None:
        try:
            values = tuple(row)
            if len(values) == 8:
                (
                    chunk_id,
                    content,
                    doc_metadata,
                    tenant_uuid_row,
                    document_uuid_row,
                    chunk_index,
                    page_number,
                    dataset_uuid_row,
                ) = values
            else:
                (
                    chunk_id,
                    content,
                    doc_metadata,
                    tenant_uuid_row,
                    document_uuid_row,
                    chunk_index,
                    page_number,
                ) = values
                dataset_uuid_row = None
        except (TypeError, ValueError, AttributeError):
            return None

        meta = dict(doc_metadata or {})
        metadata_match = _metadata_exact_anchor_match(query, meta)
        if not metadata_match:
            return None

        cid = str(chunk_id)
        match_score = float(metadata_match.get("score") or 0.0)
        meta.setdefault("tenant_id", str(tenant_uuid_row))
        meta.setdefault("document_id", str(document_uuid_row))
        meta.setdefault("chunk_index", int(chunk_index) if chunk_index is not None else None)
        meta.setdefault("chunk_id", cid)
        meta.setdefault("source", meta.get("source", "unknown"))
        effective_dataset_str = str(dataset_uuid_row) if dataset_uuid_row is not None else dataset_str
        if effective_dataset_str:
            meta.setdefault("dataset_id", effective_dataset_str)
        if page_number is not None and not meta.get("page"):
            meta["page"] = page_number
        meta.setdefault("lexical_method", "metadata_exact")
        meta["metadata_exact_candidate"] = True
        meta["metadata_exact_candidate_field"] = str(metadata_match.get("field") or "")
        meta["metadata_exact_candidate_fields"] = list(metadata_match.get("fields") or [])
        meta["metadata_exact_candidate_score"] = float(match_score)
        if metadata_filter and not self._match_metadata_filter(meta, metadata_filter):
            return None
        return cid, {
            "chunk_id": cid,
            "content": content or "",
            "metadata": meta,
            "score": max(1.0, float(match_score)),
        }

    def _search_metadata_exact_anchor_db_with_session(
        self,
        *,
        db: Session,
        query: str,
        top_k: int,
        tenant_uuid: UUID,
        document_ids: list[UUID] | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        raw_query = str(query or "").strip()
        if not raw_query or not _query_looks_like_cjk_metadata_anchor(raw_query):
            return []

        dataset_uuid, dataset_str = self._lexical_dataset_scope(metadata_filter)
        limit = max(1, int(top_k or 1))
        cap = max(1, int(getattr(settings, "RETRIEVAL_METADATA_EXACT_DB_MAX_CANDIDATES", 80) or 80))
        fetch_k = min(cap, max(limit, limit * 4))
        patterns = [f"%{self._escape_sql_like_term(term)}%" for term in self._metadata_exact_db_like_terms(raw_query)]
        if not patterns:
            return []
        metadata_text = sql_cast(DocumentChunk.doc_metadata, SQLText)
        metadata_predicate = (
            metadata_text.ilike(patterns[0], escape="\\")
            if len(patterns) == 1
            else or_(*(metadata_text.ilike(pattern, escape="\\") for pattern in patterns))
        )

        rows = (
            self._lexical_base_query(
                db,
                tenant_uuid=tenant_uuid,
                dataset_uuid=dataset_uuid,
                document_ids=document_ids,
            )
            .filter(metadata_predicate)
            .limit(fetch_k)
            .all()
        )

        results_by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            parsed = self._metadata_exact_result_from_row(
                row,
                query=raw_query,
                dataset_str=dataset_str,
                metadata_filter=metadata_filter,
            )
            if parsed is None:
                continue
            cid, result = parsed
            results_by_id[cid] = result

        if not results_by_id:
            return []

        results = list(results_by_id.values())
        results.sort(
            key=lambda item: (
                -float((item.get("metadata") or {}).get("metadata_exact_candidate_score") or 0.0),
                str(item.get("chunk_id") or ""),
            )
        )
        return results[:limit]

    def _search_metadata_exact_anchor_db(
        self,
        *,
        query: str,
        top_k: int = 10,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        raw_query = str(query or "").strip()
        if not raw_query:
            return []
        if self.metadata_exact_db_fallback_enabled is not None:
            metadata_exact_db_enabled = bool(self.metadata_exact_db_fallback_enabled)
        else:
            metadata_exact_db_enabled = bool(getattr(settings, "RETRIEVAL_METADATA_EXACT_DB_FALLBACK_ENABLED", True))
        if not metadata_exact_db_enabled:
            return []

        tenant_uuid = self._resolve_tenant_uuid(tenant_id)
        if tenant_uuid is None:
            return []

        db = self._open_session()
        try:
            bind = db.get_bind()
            if not bind or getattr(getattr(bind, "dialect", None), "name", "") != "postgresql":
                return []
            return self._search_metadata_exact_anchor_db_with_session(
                db=db,
                query=raw_query,
                top_k=top_k,
                tenant_uuid=tenant_uuid,
                document_ids=document_ids,
                metadata_filter=metadata_filter,
            )
        except Exception as exc:
            logger.debug("Metadata exact DB fallback failed: %s", exc)
            return []
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
