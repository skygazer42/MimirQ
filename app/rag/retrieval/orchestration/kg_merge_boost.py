"""KG scope resolution, KG document merge, KG chunk boost, and KG injection chunk fetch.

Split out of ``app.rag.retrieval.orchestrator`` (see
``app.rag.retrieval.orchestration``).
"""

from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from app.rag.retrieval.orchestration.common import (
    _coerce_optional_float,
    _doc_key,
    _log_orchestrator_fallback,
)


def _coerce_uuid_list(values: Any) -> list[UUID]:
    out: list[UUID] = []
    seen: set[UUID] = set()
    for value in values or []:
        try:
            item = value if isinstance(value, UUID) else UUID(str(value))
        except Exception as exc:
            _log_orchestrator_fallback("_coerce_uuid_list", exc)
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _resolve_kg_scope(state: dict[str, Any]) -> tuple[list[UUID], UUID | None, list[UUID]]:
    document_ids = _coerce_uuid_list(state.get("document_ids") or [])
    if document_ids:
        return document_ids, None, []

    dataset_id_raw = state.get("dataset_id")
    dataset_id: UUID | None = None
    if dataset_id_raw is not None:
        try:
            dataset_id = dataset_id_raw if isinstance(dataset_id_raw, UUID) else UUID(str(dataset_id_raw))
        except Exception as exc:
            _log_orchestrator_fallback("_resolve_kg_scope.dataset_id", exc)
            dataset_id = None
    if dataset_id is not None:
        return [], dataset_id, []

    return [], None, _coerce_uuid_list(state.get("dataset_ids") or [])


def _kg_signal_score(meta: dict[str, Any]) -> float:
    for key in ("kg_pagerank", "score", "retrieval_score"):
        try:
            value = meta.get(key)
            if value is None:
                continue
            return max(0.0, float(value or 0.0))
        except (TypeError, ValueError, AttributeError):
            continue
    return 0.0


def _merge_kg_metadata_into_main(main_doc: Document, kg_doc: Document) -> Document:
    main_meta = dict(main_doc.metadata or {})
    kg_meta = dict(kg_doc.metadata or {})

    main_kg_score = _kg_signal_score({"kg_pagerank": main_meta.get("kg_pagerank")})
    kg_score = _kg_signal_score(kg_meta)
    if kg_score > 0.0 or main_kg_score > 0.0:
        main_meta["kg_pagerank"] = max(main_kg_score, kg_score)

    for key in ("kg_path", "kg_path_provenance"):
        if kg_meta.get(key) and not main_meta.get(key):
            main_meta[key] = kg_meta[key]

    try:
        kg_path_length = int(kg_meta.get("kg_path_length")) if kg_meta.get("kg_path_length") is not None else None
    except (TypeError, ValueError, AttributeError):
        kg_path_length = None
    if kg_path_length is not None:
        try:
            current = int(main_meta.get("kg_path_length")) if main_meta.get("kg_path_length") is not None else None
        except (TypeError, ValueError, AttributeError):
            current = None
        main_meta["kg_path_length"] = min(current, kg_path_length) if current is not None else kg_path_length

    try:
        kg_shared_events = int(kg_meta.get("kg_shared_events")) if kg_meta.get("kg_shared_events") is not None else None
    except (TypeError, ValueError, AttributeError):
        kg_shared_events = None
    if kg_shared_events is not None:
        try:
            current = int(main_meta.get("kg_shared_events")) if main_meta.get("kg_shared_events") is not None else None
        except (TypeError, ValueError, AttributeError):
            current = None
        main_meta["kg_shared_events"] = max(current, kg_shared_events) if current is not None else kg_shared_events

    if "kg_evidence_anchored" in kg_meta:
        main_meta["kg_evidence_anchored"] = bool(main_meta.get("kg_evidence_anchored") or kg_meta.get("kg_evidence_anchored"))

    main_meta["kg_duplicate_candidate"] = True
    return Document(
        page_content=main_doc.page_content,
        metadata=main_meta,
        id=getattr(main_doc, "id", None) or main_meta.get("chunk_id"),
    )


def _merge_kg_docs_preserving_main(docs: list[Document] | None, kg_docs: list[Document] | None) -> list[Document]:
    merged = [d for d in (docs or []) if d is not None]
    index_by_key: dict[str, int] = {}
    for i, doc in enumerate(merged):
        try:
            index_by_key[_doc_key(doc)] = i
        except Exception as exc:
            _log_orchestrator_fallback("_merge_kg_docs_preserving_main", exc)

    for kg_doc in kg_docs or []:
        if kg_doc is None:
            continue
        try:
            key = _doc_key(kg_doc)
        except Exception as exc:
            _log_orchestrator_fallback("_merge_kg_docs_preserving_main", exc)
            continue
        if key in index_by_key:
            existing_index = index_by_key[key]
            merged[existing_index] = _merge_kg_metadata_into_main(merged[existing_index], kg_doc)
            continue
        index_by_key[key] = len(merged)
        merged.append(kg_doc)
    return merged


def _fetch_document_chunks_for_kg_injection(
    *,
    db: Any,
    tenant_id: Any,
    account_id: Any,
    dataset_id: Any,
    dataset_ids: list[Any] | None = None,
    document_ids: list[Any],
    chunk_ids: list[UUID],
) -> list[Any]:
    """
    Best-effort load DocumentChunk rows for KG chunk injection.

    This is intentionally a small helper so tests can monkeypatch it without setting up a real DB.
    """
    if not chunk_ids:
        return []

    if db is None or tenant_id is None:
        return []

    from app.models.document import DocumentChunk as DBDocumentChunk  # noqa: WPS433

    # Prefer explicit document_ids scope (already ACL-filtered by the API layer when present).
    if document_ids:
        return (
            db.query(DBDocumentChunk)
            .filter(
                DBDocumentChunk.tenant_id == tenant_id,
                DBDocumentChunk.document_id.in_(list(document_ids)),
                DBDocumentChunk.id.in_(list(chunk_ids)),
            )
            .all()
        )

    # Dataset-scoped retrieval: enforce dataset permission + doc-level ACL via shared helper.
    scoped_dataset_ids = _coerce_uuid_list(dataset_ids or [])
    if dataset_id is not None:
        scoped_dataset_ids = _coerce_uuid_list([dataset_id])

    if not scoped_dataset_ids or not str(account_id or "").strip():
        return []

    try:
        from sqlalchemy import or_, select  # noqa: WPS433

        from app.models.document import Document as DBDocument  # noqa: WPS433
        from app.services.dataset_profile_service import build_dataset_documents_query  # noqa: WPS433

        allowed_doc_filters = []
        for scoped_dataset_id in scoped_dataset_ids:
            _ds, q = build_dataset_documents_query(
                db,
                tenant_id=tenant_id,
                account_id=str(account_id),
                dataset_id=scoped_dataset_id,
            )
            doc_ids_subq = q.with_entities(DBDocument.id).subquery()
            allowed_doc_filters.append(DBDocumentChunk.document_id.in_(select(doc_ids_subq.c.id)))

        if not allowed_doc_filters:
            return []

        return (
            db.query(DBDocumentChunk)
            .filter(
                DBDocumentChunk.tenant_id == tenant_id,
                or_(*allowed_doc_filters),
                DBDocumentChunk.id.in_(list(chunk_ids)),
            )
            .all()
        )
    except Exception as exc:
        _log_orchestrator_fallback('_fetch_document_chunks_for_kg_injection', exc)
        return []


def _kg_chunk_boost_meta(*, enabled: bool, weight: float, max_promoted: int) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "weight": round(float(weight), 4),
        "max_promoted": int(max_promoted),
        "eligible": 0,
        "promoted": 0,
        "top_changed": False,
    }


def _kg_chunk_boost_disabled_reason(*, enabled: bool, docs: list[Document], weight: float, max_promoted: int) -> str | None:
    if enabled and docs and weight > 0.0 and max_promoted > 0:
        return None
    if not enabled:
        return "disabled"
    if weight <= 0.0:
        return "zero_weight"
    if max_promoted <= 0:
        return "zero_max_promoted"
    return "no_docs"


def _kg_boost_row(doc: Document, *, index: int, weight: float) -> dict[str, Any]:
    row_meta = dict(doc.metadata or {})
    base_raw = row_meta.get("retrieval_score")
    if base_raw is None:
        base_raw = row_meta.get("score", 0.0)
    base_score = _coerce_optional_float(base_raw, default=0.0, minimum=0.0)
    role = str(row_meta.get("retrieval_role") or "").strip().lower()
    kg_raw = row_meta.get("kg_pagerank")
    if kg_raw is None and role == "kg":
        kg_raw = row_meta.get("score", 0.0)
    kg_score = _coerce_optional_float(kg_raw, default=0.0, minimum=0.0)
    is_kg = bool(role == "kg" or kg_score > 0.0)
    boosted_score = float(base_score) + (float(weight) * float(kg_score)) if is_kg else float(base_score)
    return {
        "idx": int(index),
        "doc": doc,
        "meta": row_meta,
        "base_score": float(base_score),
        "kg_score": float(kg_score),
        "boosted_score": float(boosted_score),
        "is_kg": bool(is_kg),
    }


def _kg_boost_rows(docs: list[Document], *, weight: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    eligible_rows: list[dict[str, Any]] = []
    for index, doc in enumerate(docs):
        if not isinstance(doc, Document):
            continue
        row = _kg_boost_row(doc, index=index, weight=weight)
        rows.append(row)
        if bool(row.get("is_kg")) and float(row.get("kg_score") or 0.0) > 0.0:
            eligible_rows.append(row)
    return rows, eligible_rows


def _kg_boost_promoted_indexes(eligible_rows: list[dict[str, Any]], *, max_promoted: int) -> set[int]:
    eligible_rows.sort(
        key=lambda row: (
            -(float(row.get("boosted_score") or 0.0) - float(row.get("base_score") or 0.0)),
            -float(row.get("kg_score") or 0.0),
            int(row.get("idx") or 0),
        )
    )
    return {int(row["idx"]) for row in eligible_rows[:max_promoted]}


def _kg_boost_ranked_rows(rows: list[dict[str, Any]], *, promoted_indexes: set[int]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -(
                float(row.get("boosted_score") or 0.0)
                if int(row.get("idx") or 0) in promoted_indexes
                else float(row.get("base_score") or 0.0)
            ),
            int(row.get("idx") or 0),
        ),
    )


def _kg_boost_document(row: dict[str, Any], *, promoted_indexes: set[int]) -> tuple[Document | None, int]:
    doc = row.get("doc")
    if not isinstance(doc, Document):
        return None, 0
    doc_meta = dict(row.get("meta") or {})
    original_index = int(row.get("idx") or 0)
    if original_index in promoted_indexes:
        doc_meta["kg_boost_applied"] = True
        doc_meta["kg_boost_score"] = round(float(row.get("boosted_score") or 0.0), 6)
    out_doc = Document(
        page_content=doc.page_content,
        metadata=doc_meta,
        id=getattr(doc, "id", None) or doc_meta.get("chunk_id"),
    )
    return out_doc, original_index


def _kg_boost_output(ranked_rows: list[dict[str, Any]], *, promoted_indexes: set[int]) -> tuple[list[Document], int]:
    out: list[Document] = []
    promoted = 0
    for new_index, row in enumerate(ranked_rows):
        doc, original_index = _kg_boost_document(row, promoted_indexes=promoted_indexes)
        if doc is None:
            continue
        if original_index in promoted_indexes and new_index < original_index:
            promoted += 1
        out.append(doc)
    return out, promoted


def _apply_kg_chunk_boost(
    docs: list[Document],
    *,
    enabled: bool,
    weight: float,
    max_promoted: int,
) -> tuple[list[Document], dict[str, Any]]:
    meta = _kg_chunk_boost_meta(enabled=enabled, weight=weight, max_promoted=max_promoted)
    disabled_reason = _kg_chunk_boost_disabled_reason(
        enabled=enabled,
        docs=docs,
        weight=weight,
        max_promoted=max_promoted,
    )
    if disabled_reason is not None:
        meta["reason"] = disabled_reason
        return docs, meta

    rows, eligible_rows = _kg_boost_rows(docs, weight=weight)
    if not rows or not eligible_rows:
        meta["reason"] = "no_kg_candidates"
        return docs, meta

    promoted_indexes = _kg_boost_promoted_indexes(eligible_rows, max_promoted=max_promoted)
    meta["eligible"] = int(len(eligible_rows))
    out, promoted = _kg_boost_output(
        _kg_boost_ranked_rows(rows, promoted_indexes=promoted_indexes),
        promoted_indexes=promoted_indexes,
    )

    meta["promoted"] = int(promoted)
    meta["top_changed"] = bool(out and docs and _doc_key(out[0]) != _doc_key(docs[0]))
    meta["reason"] = "applied"
    return out, meta
