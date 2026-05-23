from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session


def _missing_relation_references_expr(column):  # noqa: ANN001
    from sqlalchemy import cast, literal, or_  # noqa: WPS433
    from sqlalchemy.dialects.postgresql import JSONB  # noqa: WPS433

    return or_(
        column.is_(None),
        cast(column, JSONB) == cast(literal({}), JSONB),
    )


def summarize_relation_noise(
    db: Session,
    *,
    tenant_id: UUID,
    document_ids: list[UUID],
    pipeline_hash: str | None,
    low_confidence_threshold: float = 0.30,
) -> dict[str, Any]:
    """
    Heuristic KG relation "noise" summary (best-effort).

    This intentionally does NOT mutate the database. It provides a lightweight signal for
    diagnostics/UI and a safe baseline before adding any LLM-based triple reflection.
    """
    if not document_ids:
        return {
            "relations_total": 0,
            "low_confidence_threshold": float(low_confidence_threshold),
            "low_confidence_relations": 0,
            "missing_references_relations": 0,
            "missing_chunk_relations": 0,
        }

    from sqlalchemy import and_, func  # noqa: WPS433

    from app.models.document import Document as DBDocument  # noqa: WPS433
    from app.rag.kg.models import KgRelation  # noqa: WPS433

    def _active_pipeline_hash_expr(doc_model):  # noqa: ANN001
        return func.coalesce(
            doc_model.doc_metadata["active_pipeline_hash"].astext,  # type: ignore[attr-defined]
            doc_model.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
        )

    def _apply_relation_pipeline_scope(query):  # noqa: ANN001
        if pipeline_hash:
            return query.filter(KgRelation.pipeline_hash == str(pipeline_hash))
        return query.join(
            DBDocument,
            and_(
                DBDocument.id == KgRelation.document_id,
                DBDocument.tenant_id == KgRelation.tenant_id,
            ),
        ).filter(KgRelation.pipeline_hash == _active_pipeline_hash_expr(DBDocument))

    base = db.query(KgRelation.id).filter(
        KgRelation.tenant_id == tenant_id,
        KgRelation.document_id.in_(document_ids),
    )
    base = _apply_relation_pipeline_scope(base)

    total = base.with_entities(func.count(KgRelation.id)).scalar() or 0
    low_conf = (
        base.with_entities(func.count(KgRelation.id))
        .filter(KgRelation.confidence < float(low_confidence_threshold))
        .scalar()
        or 0
    )
    missing_refs = (
        base.with_entities(func.count(KgRelation.id))
        .filter(_missing_relation_references_expr(KgRelation.references))
        .scalar()
        or 0
    )
    missing_chunk = (
        base.with_entities(func.count(KgRelation.id))
        .filter(KgRelation.chunk_id.is_(None))
        .scalar()
        or 0
    )

    return {
        "relations_total": int(total),
        "low_confidence_threshold": float(low_confidence_threshold),
        "low_confidence_relations": int(low_conf),
        "missing_references_relations": int(missing_refs),
        "missing_chunk_relations": int(missing_chunk),
    }


__all__ = ["summarize_relation_noise"]
