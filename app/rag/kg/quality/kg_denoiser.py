from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from sqlalchemy.orm import Query

    from app.models.knowledge_graph.entities import KgRelation


def _missing_relation_references_expr(column):  # noqa: ANN001
    from sqlalchemy import cast, or_, text  # noqa: WPS433
    from sqlalchemy.dialects.postgresql import JSONB  # noqa: WPS433

    return or_(
        column.is_(None),
        cast(column, JSONB) == cast(text("'{}'"), JSONB),
    )


def query_scoped_relations(
    db: Session, *, tenant_id: UUID, document_ids: list[UUID], pipeline_hash: str | None
) -> "Query[KgRelation]":
    from sqlalchemy import and_, func

    from app.models.documents.records import Document as DBDocument
    from app.models.knowledge_graph.entities import KgRelation

    query = db.query(KgRelation).filter(KgRelation.tenant_id == tenant_id, KgRelation.document_id.in_(document_ids))
    if pipeline_hash:
        return query.filter(KgRelation.pipeline_hash == pipeline_hash)
    active_hash = func.coalesce(
        DBDocument.doc_metadata["active_pipeline_hash"].astext,  # type: ignore[attr-defined]
        DBDocument.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
    )
    return query.join(
        DBDocument,
        and_(DBDocument.id == KgRelation.document_id, DBDocument.tenant_id == KgRelation.tenant_id),
    ).filter(KgRelation.pipeline_hash == active_hash)


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

    from sqlalchemy import func  # noqa: WPS433

    from app.models.knowledge_graph.entities import KgRelation  # noqa: WPS433

    base = query_scoped_relations(db, tenant_id=tenant_id, document_ids=document_ids, pipeline_hash=pipeline_hash)
    total, low_conf, missing_refs, missing_chunk = base.with_entities(
        func.count(KgRelation.id),
        func.count(KgRelation.id).filter(KgRelation.confidence < low_confidence_threshold),
        func.count(KgRelation.id).filter(_missing_relation_references_expr(KgRelation.references)),
        func.count(KgRelation.id).filter(KgRelation.chunk_id.is_(None)),
    ).one()

    return {
        "relations_total": int(total),
        "low_confidence_threshold": float(low_confidence_threshold),
        "low_confidence_relations": int(low_conf),
        "missing_references_relations": int(missing_refs),
        "missing_chunk_relations": int(missing_chunk),
    }


__all__ = ["query_scoped_relations", "summarize_relation_noise"]
