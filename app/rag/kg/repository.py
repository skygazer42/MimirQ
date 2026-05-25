"""
Entity and Event repositories.

Provides data access for entities and events with both PostgreSQL storage
and Milvus vector similarity search capabilities.
"""
import re
import unicodedata
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.rag.kg.models import (
    KgEntity,
    KgEntityAlias,
    KgEntityRedirect,
    KgEventEntity,
    KgRelation,
    KgSourceEvent,
)
from app.rag.retrieval.query_phrase_match import extract_informative_query_phrases
from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name

_ALIAS_TOKEN_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_+./:-]{0,64}|[\u4e00-\u9fff]{1,32}",
    flags=re.UNICODE,
)

ACCOUNT_ID_REQUIRED_WHEN_DATASET_ID_PROVIDED_ERROR = "account_id is required when dataset_id is provided"


def _allowed_document_ids_subquery_for_dataset(
    session: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    account_id: str,
):
    """
    Return a SQL subquery selecting readable document ids in a dataset.

    KG lexical fallback uses the same scope semantics as vector recall so an
    unavailable embedding provider cannot accidentally broaden access.
    """
    from app.models.document import Document as DBDocument  # noqa: WPS433
    from app.services.dataset_profile_service import build_dataset_documents_query  # noqa: WPS433

    _ds, q = build_dataset_documents_query(
        session,
        tenant_id=tenant_id,
        account_id=str(account_id or "").strip(),
        dataset_id=dataset_id,
    )
    return q.with_entities(DBDocument.id).subquery()


def _escape_like(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _lexical_score(*, query_terms: list[str], name: str, normalized_name: str, text: str = "") -> float:
    norm = str(normalized_name or "").casefold()
    display = str(name or "").casefold()
    hay = f"{display} {norm} {str(text or '').casefold()}".strip()
    if not hay:
        return 0.0

    score = 0.0
    matched = 0
    for term in query_terms:
        t = str(term or "").casefold().strip()
        if not t:
            continue
        if norm == t or display == t:
            score = max(score, 1.0)
            matched += 1
        elif t in norm or t in display:
            score = max(score, 0.88)
            matched += 1
        elif t in hay:
            score = max(score, 0.72)
            matched += 1

    if matched > 1:
        score = min(1.0, score + min(0.12, matched * 0.03))
    return float(score)


def _extract_alias_candidates(query: str, *, max_tokens: int = 32, max_ngrams: int = 256) -> list[str]:
    """
    Extract normalized alias candidates from a query string (deterministic, conservative).

    Design:
    - Avoid full substring search over all aliases (too expensive).
    - Generate a small set of candidate terms/phrases and use an indexed IN lookup on
      kg_entity_aliases.normalized_alias.
    """
    text = unicodedata.normalize("NFKC", str(query or "")).strip()
    if not text:
        return []

    tokens = [t for t in _ALIAS_TOKEN_RE.findall(text) if str(t or "").strip()]
    if not tokens:
        return []
    tokens = tokens[: max(1, int(max_tokens or 0))]

    # Candidate surfaces (unigram + short ASCII ngrams).
    surfaces: list[str] = []
    seen_s: set[str] = set()

    def _add_surface(s: str) -> None:
        s = str(s or "").strip()
        if not s:
            return
        if len(s) > 80:
            return
        sig = s.casefold() if s.isascii() else s
        if sig in seen_s:
            return
        seen_s.add(sig)
        surfaces.append(s)

    # Prefer informative multi-token phrases before generic unigrams so scoped
    # lexical KG recall does not burn its SQL budget on broad terms like "neural".
    for phrase in extract_informative_query_phrases(text, max_phrases=max_ngrams, include_unigrams=False):
        _add_surface(phrase)

    # Whole query if short (helps for exact-term queries).
    if len(text) <= 80:
        _add_surface(text)

    for tok in tokens:
        _add_surface(tok)

    # Normalize via the shared KG name normalizer so stored and query forms align.
    from app.rag.kg.extraction.parser import EntityValueParser  # noqa: WPS433

    parser = EntityValueParser()
    out: list[str] = []
    seen_n: set[str] = set()
    for surf in surfaces:
        norm = parser.normalize_name(surf)
        if not norm:
            continue
        if len(norm) > 500:
            continue
        if norm in seen_n:
            continue
        seen_n.add(norm)
        out.append(norm)
        if len(out) >= max(1, int(max_ngrams or 0)):
            break
    return out


def _active_pipeline_hash_expr(doc_model):  # noqa: ANN001
    """
    SQL expression for a document's active pipeline hash.

    Mirrors app.core.pipeline_versions.get_active_pipeline_hash semantics:
    - prefer metadata.active_pipeline_hash
    - fallback to metadata.pipeline_hash
    """
    # NOTE: JSONB ->> key compiles to bound parameters; callers can still assert
    # presence of these keys via compiled.params in tests.
    return func.coalesce(
        doc_model.doc_metadata["active_pipeline_hash"].astext,  # type: ignore[attr-defined]
        doc_model.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
    )


def _quote_milvus_str(value: str, *, max_len: int = 256) -> str:
    """
    Quote and escape a string literal for Milvus expr to avoid injection.
    Milvus uses double-quoted string literals.
    """
    text = "" if value is None else str(value)
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ValueError("Invalid string")
    if len(text) > max_len:
        raise ValueError("String too long")
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _as_uuid_list(values: Iterable[str | UUID]) -> list[UUID]:
    out: list[UUID] = []
    seen: set[UUID] = set()
    for v in values:
        if isinstance(v, UUID):
            if v in seen:
                continue
            seen.add(v)
            out.append(v)
            continue
        try:
            u = UUID(str(v))
        except Exception:
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


class EntityRepository:
    """Entity read/write + similarity search."""

    def __init__(self, session: Session):
        self.session = session
        collection = resolve_collection_name("kg_entities")
        self._milvus = get_milvus_adapter(collection_name=collection, vector_field="embedding")

    def search_similar(
        self,
        query_vector: list[float],
        tenant_id,
        k: int = 10,
        entity_type: str | None = None,
    ) -> list[dict]:
        expr_parts = [f"tenant_id == {_quote_milvus_str(str(tenant_id))}"]
        if entity_type:
            expr_parts.append(f"type == {_quote_milvus_str(entity_type)}")
        expr = " and ".join(expr_parts)

        results = self._milvus.search(query_vector=query_vector, top_k=k, expr=expr)
        formatted = []
        for r in results:
            meta = r.get("metadata") or {}
            formatted.append(
                {
                    "entity_id": meta.get("id") or r.get("id"),
                    "name": meta.get("name") or meta.get("content") or "",
                    "type": meta.get("type") or "unknown",
                    "similarity": r.get("score", 0.0),
                    "tenant_id": meta.get("tenant_id"),
                }
            )
        return formatted

    def search_lexical(
        self,
        query: str,
        tenant_id,
        k: int = 20,
        *,
        document_ids: list[UUID] | None = None,
        dataset_id: UUID | None = None,
        account_id: str | None = None,
    ) -> list[dict]:
        """
        DB-backed fallback recall for environments without KG vectors.

        It is intentionally scope-aware and conservative: only entity names that
        occur in the user query terms are returned, and dataset/document filters
        are enforced before scoring.
        """
        terms = _extract_alias_candidates(query, max_tokens=24, max_ngrams=96)
        terms = [t for t in terms if len(str(t or "").strip()) >= 2][:48]
        if not terms:
            return []
        if document_ids is not None and not document_ids:
            return []

        from sqlalchemy import and_  # noqa: WPS433

        from app.models.document import Document as DBDocument  # noqa: WPS433

        stmt = select(KgEntity).where(KgEntity.tenant_id == tenant_id)
        clauses = []
        for term in terms[:24]:
            pattern = f"%{_escape_like(term)}%"
            clauses.extend(
                [
                    KgEntity.normalized_name == term,
                    KgEntity.normalized_name.ilike(pattern, escape="\\"),
                    KgEntity.name.ilike(pattern, escape="\\"),
                ]
            )
        stmt = stmt.where(or_(*clauses))

        if document_ids is not None or dataset_id is not None:
            stmt = (
                stmt.join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
                .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
                .join(
                    DBDocument,
                    and_(
                        DBDocument.id == KgSourceEvent.document_id,
                        DBDocument.tenant_id == KgSourceEvent.tenant_id,
                    ),
                )
                .where(KgSourceEvent.pipeline_hash == _active_pipeline_hash_expr(DBDocument))
            )
            if document_ids is not None:
                stmt = stmt.where(KgSourceEvent.document_id.in_(document_ids))
            elif dataset_id is not None:
                if not account_id:
                    raise ValueError(ACCOUNT_ID_REQUIRED_WHEN_DATASET_ID_PROVIDED_ERROR)
                allowed_docs = _allowed_document_ids_subquery_for_dataset(
                    self.session,
                    tenant_id=UUID(str(tenant_id)),
                    dataset_id=dataset_id,
                    account_id=account_id,
                )
                stmt = stmt.where(KgSourceEvent.document_id.in_(select(allowed_docs.c.id)))

        rows = self.session.execute(stmt.limit(max(1, int(k)) * 8)).scalars().all()
        scored: list[dict] = []
        seen_ids: set[str] = set()
        for ent in rows:
            ent_id = str(getattr(ent, "id", "") or "")
            if not ent_id or ent_id in seen_ids:
                continue
            seen_ids.add(ent_id)
            score = _lexical_score(
                query_terms=terms,
                name=str(getattr(ent, "name", "") or ""),
                normalized_name=str(getattr(ent, "normalized_name", "") or ""),
            )
            if score <= 0:
                continue
            scored.append(
                {
                    "entity_id": ent_id,
                    "name": str(getattr(ent, "name", "") or ""),
                    "type": str(getattr(ent, "type", "") or "unknown"),
                    "similarity": float(score),
                    "tenant_id": str(tenant_id),
                    "method": "lexical_match",
                }
            )
        scored.sort(key=lambda item: (-float(item.get("similarity", 0.0) or 0.0), str(item.get("name") or "")))
        return scored[: max(1, int(k))]

    def get_entities_by_ids(self, ids: Iterable[str | UUID], *, tenant_id: UUID | None = None) -> list[KgEntity]:
        id_list = _as_uuid_list(ids)
        if not id_list:
            return []
        stmt = select(KgEntity).where(KgEntity.id.in_(id_list))
        if tenant_id is not None:
            stmt = stmt.where(KgEntity.tenant_id == tenant_id)
        return self.session.execute(stmt).scalars().all()

    def get_or_create(
        self,
        tenant_id,
        name: str,
        normalized_name: str,
        type_: str,
        description: str | None = None,
        *,
        commit: bool = True,
    ) -> KgEntity:
        existing = (
            self.session.execute(
                select(KgEntity).where(
                    KgEntity.tenant_id == tenant_id,
                    KgEntity.normalized_name == normalized_name,
                    KgEntity.type == type_,
                )
            )
            .scalars()
            .first()
        )
        if existing:
            return existing
        ent = KgEntity(
            tenant_id=tenant_id,
            name=name,
            normalized_name=normalized_name,
            type=type_,
            description=description,
            vector=None,
            extra_data=None,
        )
        self.session.add(ent)
        if commit:
            self.session.commit()
            self.session.refresh(ent)
        else:
            self.session.flush()
        return ent


class AliasRepository:
    """Alias lookup helpers for KG search and entity resolution UI."""

    def __init__(self, session: Session):
        self.session = session

    def _resolve_redirects(self, entity_ids: Iterable[UUID], *, tenant_id: UUID, max_hops: int = 6) -> dict[UUID, UUID]:
        """
        Resolve entity ids via KgEntityRedirect (best-effort, bounded).

        Returns a mapping original_id -> canonical_id (may be identity).
        """
        ids = _as_uuid_list(entity_ids)
        if not ids:
            return {}

        resolved: dict[UUID, UUID] = {eid: eid for eid in ids}
        cur = set(ids)
        hops = 0
        while cur and hops < max(1, int(max_hops or 0)):
            hops += 1
            rows = (
                self.session.query(KgEntityRedirect)
                .filter(KgEntityRedirect.tenant_id == tenant_id)
                .filter(KgEntityRedirect.from_entity_id.in_(list(cur)))
                .all()
            )
            nxt: set[UUID] = set()
            for r in rows:
                frm = getattr(r, "from_entity_id", None)
                to = getattr(r, "to_entity_id", None)
                if frm is None or to is None:
                    continue
                if resolved.get(frm) == to:
                    continue
                resolved[frm] = to
                nxt.add(to)
            cur = nxt
        return resolved

    def match_aliases(
        self,
        *,
        query: str,
        tenant_id: UUID,
        limit: int = 10,
    ) -> list[dict]:
        """
        Return alias-matched entities for the given query (lexical, deterministic).

        Output format is aligned with EntityRepository.search_similar:
          {"entity_id","name","type","similarity","tenant_id", ...}
        """
        lim = max(0, int(limit or 0))
        if lim <= 0:
            return []

        candidates = _extract_alias_candidates(query)
        if not candidates:
            return []

        # Pull alias rows first (bounded).
        rows = (
            self.session.query(KgEntityAlias)
            .filter(KgEntityAlias.tenant_id == tenant_id)
            .filter(KgEntityAlias.normalized_alias.in_(candidates))
            .order_by(KgEntityAlias.updated_at.desc(), KgEntityAlias.id.asc())
            .limit(lim * 8)
            .all()
        )
        if not rows:
            return []

        raw_entity_ids = [getattr(r, "canonical_entity_id", None) for r in rows if getattr(r, "canonical_entity_id", None)]
        resolved_map = self._resolve_redirects(raw_entity_ids, tenant_id=tenant_id)

        resolved_ids = _as_uuid_list([resolved_map.get(eid, eid) for eid in raw_entity_ids if eid is not None])
        if not resolved_ids:
            return []

        ents = (
            self.session.query(KgEntity)
            .filter(KgEntity.tenant_id == tenant_id)
            .filter(KgEntity.id.in_(resolved_ids))
            .all()
        )
        ent_by_id = {e.id: e for e in ents if getattr(e, "id", None) is not None}

        # Dedupe by resolved entity id (stable).
        out: list[dict] = []
        seen: set[str] = set()
        for r in rows:
            raw_id = getattr(r, "canonical_entity_id", None)
            if raw_id is None:
                continue
            resolved_id = resolved_map.get(raw_id, raw_id)
            ent = ent_by_id.get(resolved_id)
            if ent is None:
                continue

            sig = str(resolved_id)
            if sig in seen:
                continue
            seen.add(sig)

            out.append(
                {
                    "entity_id": str(resolved_id),
                    "name": str(getattr(ent, "name", "") or ""),
                    "type": str(getattr(ent, "type", "") or "unknown"),
                    # Treat exact alias matches as high-confidence "similarity".
                    "similarity": 1.0,
                    "tenant_id": str(tenant_id),
                    "alias_id": str(getattr(r, "id", "") or ""),
                    "alias": str(getattr(r, "alias", "") or ""),
                    "method": "alias_match",
                }
            )
            if len(out) >= lim:
                break

        return out


class EventRepository:
    """Event read/write + similarity search."""

    def __init__(self, session: Session):
        self.session = session
        collection = resolve_collection_name("kg_events")
        self._milvus = get_milvus_adapter(collection_name=collection, vector_field="embedding")

    def _allowed_document_ids_subquery_for_dataset(self, *, tenant_id: UUID, dataset_id: UUID, account_id: str):
        """
        Return a SQL subquery selecting document ids within dataset that `account_id` can read.

        Notes:
        - Enforces dataset permission + document-level ACL (security trimming).
        - Uses the shared semantics in dataset_profile_service to stay consistent with chat/retrieval.
        """
        return _allowed_document_ids_subquery_for_dataset(
            self.session,
            tenant_id=tenant_id,
            account_id=str(account_id or "").strip(),
            dataset_id=dataset_id,
        )

    def filter_event_ids_in_dataset(
        self,
        event_ids: Iterable[str | UUID],
        *,
        tenant_id: UUID,
        dataset_id: UUID,
        account_id: str,
    ) -> set[UUID]:
        ids = _as_uuid_list(event_ids)
        if not ids:
            return set()
        from sqlalchemy import and_  # noqa: WPS433

        from app.models.document import Document as DBDocument  # noqa: WPS433

        allowed_docs = self._allowed_document_ids_subquery_for_dataset(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            account_id=account_id,
        )
        stmt = (
            select(KgSourceEvent.id)
            .join(
                DBDocument,
                and_(
                    DBDocument.id == KgSourceEvent.document_id,
                    DBDocument.tenant_id == KgSourceEvent.tenant_id,
                ),
            )
            .where(
                KgSourceEvent.tenant_id == tenant_id,
                KgSourceEvent.id.in_(ids),
                KgSourceEvent.document_id.in_(select(allowed_docs.c.id)),
                KgSourceEvent.pipeline_hash == _active_pipeline_hash_expr(DBDocument),
            )
            .distinct()
        )
        return set(self.session.execute(stmt).scalars().all())

    def filter_event_ids_in_documents(
        self,
        event_ids: Iterable[str | UUID],
        *,
        tenant_id: UUID,
        document_ids: Iterable[str | UUID],
    ) -> set[UUID]:
        ids = _as_uuid_list(event_ids)
        doc_ids = _as_uuid_list(document_ids)
        if not ids or not doc_ids:
            return set()

        from sqlalchemy import and_  # noqa: WPS433

        from app.models.document import Document as DBDocument  # noqa: WPS433

        stmt = (
            select(KgSourceEvent.id)
            .join(
                DBDocument,
                and_(
                    DBDocument.id == KgSourceEvent.document_id,
                    DBDocument.tenant_id == KgSourceEvent.tenant_id,
                ),
            )
            .where(
                KgSourceEvent.tenant_id == tenant_id,
                KgSourceEvent.id.in_(ids),
                KgSourceEvent.document_id.in_(doc_ids),
                KgSourceEvent.pipeline_hash == _active_pipeline_hash_expr(DBDocument),
            )
            .distinct()
        )
        return set(self.session.execute(stmt).scalars().all())

    def filter_entity_ids_in_dataset(
        self,
        entity_ids: Iterable[str | UUID],
        *,
        tenant_id: UUID,
        dataset_id: UUID,
        account_id: str,
    ) -> set[UUID]:
        ids = _as_uuid_list(entity_ids)
        if not ids:
            return set()
        from sqlalchemy import and_  # noqa: WPS433

        from app.models.document import Document as DBDocument  # noqa: WPS433

        allowed_docs = self._allowed_document_ids_subquery_for_dataset(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            account_id=account_id,
        )
        stmt = (
            select(KgEventEntity.entity_id)
            .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
            .join(
                DBDocument,
                and_(
                    DBDocument.id == KgSourceEvent.document_id,
                    DBDocument.tenant_id == KgSourceEvent.tenant_id,
                ),
            )
            .where(
                KgSourceEvent.tenant_id == tenant_id,
                KgSourceEvent.document_id.in_(select(allowed_docs.c.id)),
                KgSourceEvent.pipeline_hash == _active_pipeline_hash_expr(DBDocument),
                KgEventEntity.entity_id.in_(ids),
            )
            .distinct()
        )
        return set(self.session.execute(stmt).scalars().all())

    def link_event_entities(
        self,
        links: list[KgEventEntity],
    ) -> None:
        for link in links:
            self.session.merge(link)
        self.session.commit()

    def get_events_by_ids(
        self,
        ids: Iterable[str | UUID],
        *,
        tenant_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
        dataset_id: UUID | None = None,
        account_id: str | None = None,
    ) -> list[KgSourceEvent]:
        id_list = _as_uuid_list(ids)
        if not id_list:
            return []
        if document_ids is not None and not document_ids:
            # Explicit empty scope must never broaden to tenant-wide reads.
            return []
        stmt = select(KgSourceEvent).where(KgSourceEvent.id.in_(id_list))
        if tenant_id is not None:
            stmt = stmt.where(KgSourceEvent.tenant_id == tenant_id)
        if document_ids is not None:
            stmt = stmt.where(KgSourceEvent.document_id.in_(document_ids))
        elif dataset_id is not None:
            if tenant_id is None:
                raise ValueError("tenant_id is required when dataset_id is provided")
            if not account_id:
                raise ValueError(ACCOUNT_ID_REQUIRED_WHEN_DATASET_ID_PROVIDED_ERROR)
            allowed_docs = self._allowed_document_ids_subquery_for_dataset(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                account_id=account_id,
            )
            stmt = stmt.where(KgSourceEvent.document_id.in_(select(allowed_docs.c.id)))

        # Versioning: when scoped to a set of documents, avoid leaking stale events from
        # inactive pipeline versions by enforcing document.active_pipeline_hash.
        if document_ids is not None or dataset_id is not None:
            from sqlalchemy import and_  # noqa: WPS433

            from app.models.document import Document as DBDocument  # noqa: WPS433

            stmt = stmt.join(
                DBDocument,
                and_(
                    DBDocument.id == KgSourceEvent.document_id,
                    DBDocument.tenant_id == KgSourceEvent.tenant_id,
                ),
            ).where(KgSourceEvent.pipeline_hash == _active_pipeline_hash_expr(DBDocument))
        return self.session.execute(stmt).scalars().all()

    def get_events_with_entities(self, ids: Iterable[str | UUID], *, tenant_id: UUID | None = None) -> list[KgSourceEvent]:
        id_list = _as_uuid_list(ids)
        if not id_list:
            return []
        from sqlalchemy.orm import joinedload

        stmt = (
            select(KgSourceEvent)
            .where(KgSourceEvent.id.in_(id_list))
            .options(
                joinedload(KgSourceEvent.associations).joinedload(KgEventEntity.entity)
            )
        )
        if tenant_id is not None:
            stmt = stmt.where(KgSourceEvent.tenant_id == tenant_id)
        return self.session.execute(stmt).scalars().all()

    def search_similar_by_content(
        self,
        query_vector: list[float],
        tenant_id,
        k: int = 20,
        document_ids: list[UUID] | None = None,
        dataset_id: UUID | None = None,
        account_id: str | None = None,
    ) -> list[dict]:
        expr_parts = [f"tenant_id == {_quote_milvus_str(str(tenant_id))}"]
        if document_ids is not None and not document_ids:
            # Explicit empty scope must never broaden vector search to the full tenant.
            return []
        if document_ids is not None:
            doc_id_strs = [_quote_milvus_str(str(doc_id)) for doc_id in document_ids[:500]]
            expr_parts.append(f"document_id in [{', '.join(doc_id_strs)}]")
        expr = " and ".join(expr_parts)
        # Best-effort: over-fetch when we will post-filter by ACL/pipeline so we can still
        # return close to k results after trimming.
        want_k = max(1, int(k))
        fetch_k = want_k
        if document_ids is not None or dataset_id is not None:
            fetch_k = min(max(want_k, want_k * 5), 500)

        results = self._milvus.search(query_vector=query_vector, top_k=fetch_k, expr=expr)
        formatted = []
        for r in results:
            meta = r.get("metadata") or {}
            formatted.append(
                {
                    "event_id": meta.get("id") or r.get("id"),
                    "title": meta.get("title") or "",
                    "summary": meta.get("summary") or "",
                    "similarity": r.get("score", 0.0),
                    "tenant_id": meta.get("tenant_id"),
                    "chunk_id": meta.get("chunk_id"),
                    "document_id": meta.get("document_id"),
                }
            )

        # Document-scoped search: post-filter to active pipeline to prevent stale KG drift.
        if document_ids is not None:
            try:
                candidate_event_ids = [item.get("event_id") for item in formatted if item.get("event_id")]
                allowed_event_ids = self.filter_event_ids_in_documents(
                    candidate_event_ids,
                    tenant_id=UUID(str(tenant_id)),
                    document_ids=document_ids,
                )
                allowed_strs = {str(eid) for eid in allowed_event_ids}
                return [item for item in formatted if str(item.get("event_id")) in allowed_strs][:want_k]
            except Exception:
                return formatted[:want_k]

        if dataset_id is None:
            return formatted[:want_k]

        # Dataset-scoped search: post-filter vector hits via SQL to enforce ACL without enumerating doc ids.
        if not account_id:
            raise ValueError(ACCOUNT_ID_REQUIRED_WHEN_DATASET_ID_PROVIDED_ERROR)
        try:
            candidate_event_ids = [item.get("event_id") for item in formatted if item.get("event_id")]
            allowed_event_ids = self.filter_event_ids_in_dataset(
                candidate_event_ids,
                tenant_id=UUID(str(tenant_id)),
                dataset_id=dataset_id,
                account_id=account_id,
            )
            allowed_strs = {str(eid) for eid in allowed_event_ids}
            return [item for item in formatted if str(item.get("event_id")) in allowed_strs][:want_k]
        except Exception:
            # Best-effort: if filtering fails, fall back to raw vector hits (caller can still filter later).
            return formatted[:want_k]

    def search_events_lexical(
        self,
        query: str,
        tenant_id,
        k: int = 20,
        *,
        document_ids: list[UUID] | None = None,
        dataset_id: UUID | None = None,
        account_id: str | None = None,
    ) -> list[dict]:
        """DB-backed event fallback when query/event vectors are unavailable."""
        terms = _extract_alias_candidates(query, max_tokens=24, max_ngrams=96)
        terms = [t for t in terms if len(str(t or "").strip()) >= 2][:48]
        if not terms:
            return []
        if document_ids is not None and not document_ids:
            return []

        from sqlalchemy import and_  # noqa: WPS433

        from app.models.document import Document as DBDocument  # noqa: WPS433

        stmt = select(KgSourceEvent).where(KgSourceEvent.tenant_id == tenant_id)
        clauses = []
        rank_expr = None
        for term in terms[:24]:
            pattern = f"%{_escape_like(term)}%"
            token_count = max(1, len(str(term).split()))
            weight = float(min(4, token_count))
            clauses.extend(
                [
                    KgSourceEvent.title.ilike(pattern, escape="\\"),
                    KgSourceEvent.summary.ilike(pattern, escape="\\"),
                    KgSourceEvent.content.ilike(pattern, escape="\\"),
                ]
            )
            term_rank = (
                case((KgSourceEvent.title.ilike(pattern, escape="\\"), weight * 1.0), else_=0.0)
                + case((KgSourceEvent.summary.ilike(pattern, escape="\\"), weight * 0.8), else_=0.0)
                + case((KgSourceEvent.content.ilike(pattern, escape="\\"), weight * 0.6), else_=0.0)
            )
            rank_expr = term_rank if rank_expr is None else rank_expr + term_rank
        stmt = stmt.where(or_(*clauses))

        if document_ids is not None or dataset_id is not None:
            stmt = stmt.join(
                DBDocument,
                and_(
                    DBDocument.id == KgSourceEvent.document_id,
                    DBDocument.tenant_id == KgSourceEvent.tenant_id,
                ),
            ).where(KgSourceEvent.pipeline_hash == _active_pipeline_hash_expr(DBDocument))
            if document_ids is not None:
                stmt = stmt.where(KgSourceEvent.document_id.in_(document_ids))
            elif dataset_id is not None:
                if not account_id:
                    raise ValueError(ACCOUNT_ID_REQUIRED_WHEN_DATASET_ID_PROVIDED_ERROR)
                allowed_docs = self._allowed_document_ids_subquery_for_dataset(
                    tenant_id=UUID(str(tenant_id)),
                    dataset_id=dataset_id,
                    account_id=account_id,
                )
                stmt = stmt.where(KgSourceEvent.document_id.in_(select(allowed_docs.c.id)))

        rows = (
            self.session.execute(
                stmt.order_by(
                    (rank_expr.desc() if rank_expr is not None else KgSourceEvent.updated_at.desc()),
                    KgSourceEvent.updated_at.desc(),
                    KgSourceEvent.id.asc(),
                ).limit(max(1, int(k)) * 10)
            )
            .scalars()
            .all()
        )
        scored: list[dict] = []
        for ev in rows:
            score = _lexical_score(
                query_terms=terms,
                name=str(getattr(ev, "title", "") or ""),
                normalized_name=str(getattr(ev, "title", "") or ""),
                text=f"{getattr(ev, 'summary', '') or ''} {getattr(ev, 'content', '') or ''}",
            )
            if score <= 0:
                continue
            scored.append(
                {
                    "event_id": str(getattr(ev, "id", "") or ""),
                    "title": str(getattr(ev, "title", "") or ""),
                    "summary": str(getattr(ev, "summary", "") or ""),
                    "similarity": float(score),
                    "tenant_id": str(tenant_id),
                    "chunk_id": str(getattr(ev, "chunk_id", "") or ""),
                    "document_id": str(getattr(ev, "document_id", "") or ""),
                    "method": "lexical_match",
                }
            )
        scored.sort(key=lambda item: (-float(item.get("similarity", 0.0) or 0.0), str(item.get("event_id") or "")))
        return scored[: max(1, int(k))]

    def search_events_by_entities(
        self,
        entity_ids: Iterable[str | UUID],
        tenant_id,
        limit: int = 50,
        document_ids: list[UUID] | None = None,
        dataset_id: UUID | None = None,
        account_id: str | None = None,
    ) -> list[UUID]:
        ids = _as_uuid_list(entity_ids)
        if not ids:
            return []
        if document_ids is not None and not document_ids:
            # Explicit empty scope must never broaden to tenant-wide reads.
            return []
        # Prefer stronger edges when ranking events by related entities.
        #
        # Notes:
        # - `kg_event_entities.weight` is used for skill links and can be extended later for
        #   entity confidence. Using it here improves recall ordering without changing semantics
        #   when all weights are 1.0.
        weight_sum = func.sum(KgEventEntity.weight).label("weight_sum")
        ent_count = func.count(KgEventEntity.entity_id).label("cnt")
        stmt = (
            select(
                KgEventEntity.event_id,
                weight_sum,
                ent_count,
            )
            .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
            .where(KgEventEntity.entity_id.in_(ids))
            .where(KgSourceEvent.tenant_id == tenant_id)
            .group_by(KgEventEntity.event_id)
            .order_by(
                weight_sum.desc(),
                ent_count.desc(),
                KgEventEntity.event_id.asc(),
            )
            .limit(limit)
        )
        if document_ids is not None:
            stmt = stmt.where(KgSourceEvent.document_id.in_(document_ids))
        elif dataset_id is not None:
            if not account_id:
                raise ValueError(ACCOUNT_ID_REQUIRED_WHEN_DATASET_ID_PROVIDED_ERROR)
            allowed_docs = self._allowed_document_ids_subquery_for_dataset(
                tenant_id=UUID(str(tenant_id)),
                dataset_id=dataset_id,
                account_id=account_id,
            )
            stmt = stmt.where(KgSourceEvent.document_id.in_(select(allowed_docs.c.id)))

        if document_ids is not None or dataset_id is not None:
            from sqlalchemy import and_  # noqa: WPS433

            from app.models.document import Document as DBDocument  # noqa: WPS433

            stmt = stmt.join(
                DBDocument,
                and_(
                    DBDocument.id == KgSourceEvent.document_id,
                    DBDocument.tenant_id == KgSourceEvent.tenant_id,
                ),
            ).where(KgSourceEvent.pipeline_hash == _active_pipeline_hash_expr(DBDocument))
        rows = self.session.execute(stmt).all()
        return [row[0] for row in rows]

    def filter_entity_ids_in_documents(
        self,
        entity_ids: Iterable[str | UUID],
        *,
        tenant_id: UUID,
        document_ids: list[UUID],
    ) -> set[UUID]:
        ids = _as_uuid_list(entity_ids)
        if not ids or not document_ids:
            return set()
        from sqlalchemy import and_  # noqa: WPS433

        from app.models.document import Document as DBDocument  # noqa: WPS433

        stmt = (
            select(KgEventEntity.entity_id)
            .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
            .join(
                DBDocument,
                and_(
                    DBDocument.id == KgSourceEvent.document_id,
                    DBDocument.tenant_id == KgSourceEvent.tenant_id,
                ),
            )
            .where(
                KgSourceEvent.tenant_id == tenant_id,
                KgSourceEvent.document_id.in_(document_ids),
                KgSourceEvent.pipeline_hash == _active_pipeline_hash_expr(DBDocument),
                KgEventEntity.entity_id.in_(ids),
            )
            .distinct()
        )
        return set(self.session.execute(stmt).scalars().all())

    def get_event_entities(
        self,
        event_ids: Iterable[str | UUID],
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, list[KgEventEntity]]:
        ids = _as_uuid_list(event_ids)
        if not ids:
            return {}
        stmt = select(KgEventEntity).where(KgEventEntity.event_id.in_(ids))
        if tenant_id is not None:
            stmt = stmt.join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id).where(
                KgSourceEvent.tenant_id == tenant_id
            )
        rows = self.session.execute(stmt).scalars().all()
        mapping: dict[str, list[KgEventEntity]] = {}
        for row in rows:
            mapping.setdefault(str(row.event_id), []).append(row)
        return mapping

    def get_entities_for_events(
        self,
        event_ids: Iterable[str | UUID],
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, list[KgEntity]]:
        ids = _as_uuid_list(event_ids)
        if not ids:
            return {}
        stmt = (
            select(KgEventEntity, KgEntity)
            .join(KgEntity, KgEntity.id == KgEventEntity.entity_id)
            .where(KgEventEntity.event_id.in_(ids))
        )
        if tenant_id is not None:
            stmt = (
                stmt.join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
                .where(KgSourceEvent.tenant_id == tenant_id)
                .where(KgEntity.tenant_id == tenant_id)
            )
        rows = self.session.execute(stmt).all()
        mapping: dict[str, list[KgEntity]] = {}
        for assoc, ent in rows:
            mapping.setdefault(str(assoc.event_id), []).append(ent)
        return mapping

    def find_events_by_entities(
        self,
        entity_ids: Iterable[str | UUID],
        tenant_id,
        limit: int = 50,
        document_ids: list[UUID] | None = None,
        dataset_id: UUID | None = None,
        account_id: str | None = None,
    ) -> list[KgSourceEvent]:
        ids = _as_uuid_list(entity_ids)
        if not ids:
            return []
        if document_ids is not None and not document_ids:
            # Explicit empty scope must never broaden to tenant-wide reads.
            return []
        stmt = (
            select(KgSourceEvent)
            .join(KgEventEntity, KgEventEntity.event_id == KgSourceEvent.id)
            .where(KgEventEntity.entity_id.in_(ids))
            .where(KgSourceEvent.tenant_id == tenant_id)
            .group_by(KgSourceEvent.id)
            .order_by(func.count(KgEventEntity.entity_id).desc(), KgSourceEvent.updated_at.desc())
            .limit(limit)
        )
        if document_ids is not None:
            stmt = stmt.where(KgSourceEvent.document_id.in_(document_ids))
        elif dataset_id is not None:
            if not account_id:
                raise ValueError(ACCOUNT_ID_REQUIRED_WHEN_DATASET_ID_PROVIDED_ERROR)
            allowed_docs = self._allowed_document_ids_subquery_for_dataset(
                tenant_id=UUID(str(tenant_id)),
                dataset_id=dataset_id,
                account_id=account_id,
            )
            stmt = stmt.where(KgSourceEvent.document_id.in_(select(allowed_docs.c.id)))

        if document_ids is not None or dataset_id is not None:
            from sqlalchemy import and_  # noqa: WPS433

            from app.models.document import Document as DBDocument  # noqa: WPS433

            stmt = stmt.join(
                DBDocument,
                and_(
                    DBDocument.id == KgSourceEvent.document_id,
                    DBDocument.tenant_id == KgSourceEvent.tenant_id,
                ),
            ).where(KgSourceEvent.pipeline_hash == _active_pipeline_hash_expr(DBDocument))
        return self.session.execute(stmt).scalars().all()


class RelationRepository:
    """Relation (entity-entity) read/write helpers."""

    def __init__(self, session: Session):
        self.session = session

    def _allowed_document_ids_subquery_for_dataset(self, *, tenant_id: UUID, dataset_id: UUID, account_id: str):
        """
        Return a SQL subquery selecting document ids within dataset that `account_id` can read.

        Mirrors the semantics in EventRepository._allowed_document_ids_subquery_for_dataset so that
        relation search respects document-level ACL (security trimming).
        """
        from app.models.document import Document as DBDocument  # noqa: WPS433
        from app.services.dataset_profile_service import build_dataset_documents_query  # noqa: WPS433

        _ds, q = build_dataset_documents_query(
            self.session,
            tenant_id=tenant_id,
            account_id=str(account_id or "").strip(),
            dataset_id=dataset_id,
        )
        return q.with_entities(DBDocument.id).subquery()

    def list_relations_for_entities(
        self,
        entity_ids: Iterable[str | UUID],
        *,
        tenant_id: UUID,
        document_ids: list[UUID] | None = None,
        dataset_id: UUID | None = None,
        account_id: str | None = None,
        min_confidence: float | None = None,
        allowed_predicates: Iterable[str] | None = None,
        limit: int = 2000,
    ) -> list[KgRelation]:
        """
        List relations where either endpoint is within `entity_ids`.

        Notes:
        - Enforces tenant scope.
        - Optional: enforce document scope (document_ids or dataset_id+account_id).
        - Optional: filter by confidence and/or predicate allowlist.
        """
        ids = _as_uuid_list(entity_ids)
        if not ids:
            return []

        lim = max(0, int(limit))
        q = (
            self.session.query(KgRelation)
            .filter(KgRelation.tenant_id == tenant_id)
            .filter(or_(KgRelation.subject_entity_id.in_(ids), KgRelation.object_entity_id.in_(ids)))
        )

        if min_confidence is not None:
            q = q.filter(KgRelation.confidence >= float(min_confidence))

        if allowed_predicates:
            preds = [str(p).strip() for p in allowed_predicates if str(p).strip()]
            if preds:
                q = q.filter(KgRelation.predicate.in_(preds))

        if document_ids is not None:
            doc_ids = _as_uuid_list(document_ids)
            if not doc_ids:
                # Explicit empty scope must never broaden to tenant-wide reads.
                return []
            q = q.filter(KgRelation.document_id.in_(doc_ids))
        elif dataset_id is not None:
            if not account_id:
                raise ValueError(ACCOUNT_ID_REQUIRED_WHEN_DATASET_ID_PROVIDED_ERROR)
            allowed_docs = self._allowed_document_ids_subquery_for_dataset(
                tenant_id=UUID(str(tenant_id)),
                dataset_id=dataset_id,
                account_id=account_id,
            )
            q = q.filter(KgRelation.document_id.in_(select(allowed_docs.c.id)))

        if document_ids is not None or dataset_id is not None:
            from sqlalchemy import and_  # noqa: WPS433

            from app.models.document import Document as DBDocument  # noqa: WPS433

            q = q.join(
                DBDocument,
                and_(
                    DBDocument.id == KgRelation.document_id,
                    DBDocument.tenant_id == KgRelation.tenant_id,
                ),
            ).filter(KgRelation.pipeline_hash == _active_pipeline_hash_expr(DBDocument))

        q = q.order_by(KgRelation.updated_at.desc())
        if lim:
            q = q.limit(lim)
        return list(q.all())

    def delete_relations_for_chunks(
        self,
        chunk_ids: Iterable[str | UUID],
        *,
        tenant_id: UUID,
        commit: bool = True,
    ) -> int:
        ids = _as_uuid_list(chunk_ids)
        if not ids:
            return 0
        deleted = int(
            self.session.query(KgRelation)
            .filter(KgRelation.tenant_id == tenant_id, KgRelation.chunk_id.in_(ids))
            .delete(synchronize_session=False)
            or 0
        )
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return deleted

    def list_relations_for_documents(
        self,
        *,
        tenant_id: UUID,
        document_ids: Iterable[str | UUID],
        limit: int = 2000,
    ) -> list[KgRelation]:
        ids = _as_uuid_list(document_ids)
        if not ids:
            return []

        lim = max(0, int(limit))
        q = (
            self.session.query(KgRelation)
            .filter(KgRelation.tenant_id == tenant_id, KgRelation.document_id.in_(ids))
            .order_by(KgRelation.updated_at.desc())
        )
        if lim:
            q = q.limit(lim)
        return list(q.all())


def get_session() -> Session:
    return SessionLocal()
