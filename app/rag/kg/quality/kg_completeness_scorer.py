
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.kg.quality.kg_denoiser import summarize_relation_noise


@dataclass
class _UnionFind:
    parent: dict[str, str]
    size: dict[str, int]

    @classmethod
    def from_nodes(cls, nodes: set[str]) -> "_UnionFind":
        parent = {n: n for n in nodes}
        size = dict.fromkeys(nodes, 1)
        return cls(parent=parent, size=size)

    def find(self, x: str) -> str:
        # Path compression.
        p = self.parent.get(x, x)
        if p != x:
            p = self.find(p)
            self.parent[x] = p
        return p

    def union(self, a: str, b: str) -> None:
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return
        sa = int(self.size.get(ra, 1))
        sb = int(self.size.get(rb, 1))
        # Union by size.
        if sa < sb:
            ra, rb = rb, ra
            sa, sb = sb, sa
        self.parent[rb] = ra
        self.size[ra] = sa + sb
        self.size.pop(rb, None)


def _active_pipeline_hash_expr(doc_model):  # noqa: ANN001
    from sqlalchemy import func  # noqa: WPS433

    return func.coalesce(
        doc_model.doc_metadata["active_pipeline_hash"].astext,  # type: ignore[attr-defined]
        doc_model.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
    )


def _apply_event_pipeline_scope(query, *, pipeline_hash: str | None):  # noqa: ANN001
    from sqlalchemy import and_  # noqa: WPS433

    from app.models.document import Document as DBDocument  # noqa: WPS433
    from app.rag.kg.models import KgSourceEvent  # noqa: WPS433

    if pipeline_hash:
        return query.filter(KgSourceEvent.pipeline_hash == str(pipeline_hash))

    return query.join(
        DBDocument,
        and_(
            DBDocument.id == KgSourceEvent.document_id,
            DBDocument.tenant_id == KgSourceEvent.tenant_id,
        ),
    ).filter(KgSourceEvent.pipeline_hash == _active_pipeline_hash_expr(DBDocument))


def _apply_relation_pipeline_scope(query, *, pipeline_hash: str | None):  # noqa: ANN001
    from sqlalchemy import and_  # noqa: WPS433

    from app.models.document import Document as DBDocument  # noqa: WPS433
    from app.rag.kg.models import KgRelation  # noqa: WPS433

    if pipeline_hash:
        return query.filter(KgRelation.pipeline_hash == str(pipeline_hash))

    return query.join(
        DBDocument,
        and_(
            DBDocument.id == KgRelation.document_id,
            DBDocument.tenant_id == KgRelation.tenant_id,
        ),
    ).filter(KgRelation.pipeline_hash == _active_pipeline_hash_expr(DBDocument))


def _connectivity_metrics(*, nodes: set[str], edges: list[tuple[str, str]]) -> dict[str, Any]:
    if not nodes:
        return {
            "nodes": 0,
            "edges": int(len(edges or [])),
            "components": 0,
            "largest_component_size": 0,
            "largest_component_ratio": 0.0,
            "components_top_sizes": [],
        }

    uf = _UnionFind.from_nodes(nodes)
    for a, b in edges or []:
        if a in uf.parent and b in uf.parent and a != b:
            uf.union(a, b)

    sizes = sorted([int(s) for s in uf.size.values()], reverse=True)
    comp = len(sizes)
    largest = sizes[0] if sizes else 0
    return {
        "nodes": int(len(nodes)),
        "edges": int(len(edges or [])),
        "components": int(comp),
        "largest_component_size": int(largest),
        "largest_component_ratio": float(largest / max(1, len(nodes))),
        "components_top_sizes": [int(x) for x in sizes[:10]],
    }


def build_kg_quality_report(
    db: Session,
    *,
    tenant_id: UUID,
    document_ids: list[UUID],
    pipeline_hash: str | None = None,
) -> dict[str, Any]:
    """
    Build a KG extraction quality report (best-effort, PII-minimal).

    Notes:
    - This report is intentionally aggregate-only (counts/ratios). It must not leak raw chunk text.
    - The "coverage" score here is heuristic. It primarily reflects graph structure + provenance completeness.
    """
    if not document_ids:
        return {
            "summary": {
                "documents": 0,
                "events": 0,
                "entities": 0,
                "relations": 0,
                "event_entity_links": 0,
                "avg_relations_per_entity": 0.0,
                "isolated_entity_ratio": 0.0,
            },
            "components": {"nodes": 0, "edges": 0, "components": 0, "largest_component_ratio": 0.0},
            "noise": summarize_relation_noise(
                db,
                tenant_id=tenant_id,
                document_ids=document_ids,
                pipeline_hash=pipeline_hash,
            ),
            "truncation": {"relation_edges_truncated": False, "relation_edges_limit": 0},
        }

    from sqlalchemy import func, union_all  # noqa: WPS433

    from app.rag.kg.models import KgEventEntity, KgRelation, KgSourceEvent  # noqa: WPS433

    # Events + entity links (scoped by allowed docs + pipeline).
    events_q = db.query(func.count(KgSourceEvent.id)).filter(
        KgSourceEvent.tenant_id == tenant_id,
        KgSourceEvent.document_id.in_(document_ids),
    )
    events_q = _apply_event_pipeline_scope(events_q, pipeline_hash=pipeline_hash)
    event_count = int(events_q.scalar() or 0)

    links_q = (
        db.query(func.count(KgEventEntity.id))
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(document_ids),
        )
    )
    links_q = _apply_event_pipeline_scope(links_q, pipeline_hash=pipeline_hash)
    link_count = int(links_q.scalar() or 0)

    entity_count_q = (
        db.query(func.count(func.distinct(KgEventEntity.entity_id)))
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(document_ids),
        )
    )
    entity_count_q = _apply_event_pipeline_scope(entity_count_q, pipeline_hash=pipeline_hash)
    entity_count = int(entity_count_q.scalar() or 0)

    # Relations (triples) are document-scoped (with provenance).
    relation_count_q = db.query(func.count(KgRelation.id)).filter(
        KgRelation.tenant_id == tenant_id,
        KgRelation.document_id.in_(document_ids),
    )
    relation_count_q = _apply_relation_pipeline_scope(relation_count_q, pipeline_hash=pipeline_hash)
    relation_count = int(relation_count_q.scalar() or 0)

    # How many entities participate in at least one relation (degree>0).
    rel_sub = (
        db.query(KgRelation.subject_entity_id.label("eid"))
        .filter(
            KgRelation.tenant_id == tenant_id,
            KgRelation.document_id.in_(document_ids),
        )
    )
    rel_obj = (
        db.query(KgRelation.object_entity_id.label("eid"))
        .filter(
            KgRelation.tenant_id == tenant_id,
            KgRelation.document_id.in_(document_ids),
        )
    )
    rel_sub = _apply_relation_pipeline_scope(rel_sub, pipeline_hash=pipeline_hash)
    rel_obj = _apply_relation_pipeline_scope(rel_obj, pipeline_hash=pipeline_hash)
    rel_union = union_all(rel_sub, rel_obj).subquery()
    rel_participants = int(db.query(func.count(func.distinct(rel_union.c.eid))).scalar() or 0)

    isolated = max(0, int(entity_count) - int(rel_participants))
    isolated_ratio = float(isolated / max(1, int(entity_count)))

    avg_rel_per_entity = float((2 * relation_count) / max(1, int(entity_count)))

    # Connected components over relation graph (best-effort; capped).
    edge_limit = int(settings.KG_QUALITY_RELATION_EDGES_LIMIT)
    edge_limit = max(0, edge_limit)
    rel_edges_truncated = False
    edges: list[tuple[str, str]] = []
    nodes: set[str] = set()
    if relation_count > 0 and edge_limit != 0:
        edges_q = db.query(KgRelation.subject_entity_id, KgRelation.object_entity_id).filter(
            KgRelation.tenant_id == tenant_id,
            KgRelation.document_id.in_(document_ids),
        )
        edges_q = _apply_relation_pipeline_scope(edges_q, pipeline_hash=pipeline_hash)
        if edge_limit > 0:
            edges_q = edges_q.limit(edge_limit + 1)
        rows = edges_q.all()
        if edge_limit > 0 and len(rows) > edge_limit:
            rel_edges_truncated = True
            rows = rows[:edge_limit]
        for a, b in rows:
            if a is None or b is None:
                continue
            sa = str(a)
            sb = str(b)
            if not sa or not sb:
                continue
            edges.append((sa, sb))
            nodes.add(sa)
            nodes.add(sb)

    components = _connectivity_metrics(nodes=nodes, edges=edges)

    noise = summarize_relation_noise(
        db,
        tenant_id=tenant_id,
        document_ids=document_ids,
        pipeline_hash=pipeline_hash,
        low_confidence_threshold=float(getattr(settings, "KG_QUALITY_LOW_CONFIDENCE_THRESHOLD", 0.30) or 0.30),
    )

    return {
        "summary": {
            "documents": int(len(document_ids)),
            "events": int(event_count),
            "entities": int(entity_count),
            "relations": int(relation_count),
            "event_entity_links": int(link_count),
            "avg_relations_per_entity": float(round(avg_rel_per_entity, 4)),
            "isolated_entities": int(isolated),
            "isolated_entity_ratio": float(round(isolated_ratio, 4)),
        },
        "components": components,
        "noise": noise,
        "truncation": {
            "relation_edges_truncated": bool(rel_edges_truncated),
            "relation_edges_limit": int(edge_limit),
        },
    }


__all__ = ["build_kg_quality_report"]
