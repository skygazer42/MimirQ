"""
Predicate ontology helpers (Wave15).

Goal:
- Provide a DB-governed allowlist for KG relation predicates.
- Keep extraction/search deterministic and auditable while allowing UI edits.

Design:
- If the DB table has any enabled predicates for the tenant, we prefer it.
- Otherwise, fall back to settings.KG_RELATION_ALLOWED_PREDICATES (if set),
  then the extractor's built-in defaults.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session


def load_enabled_predicates(db: Session, *, tenant_id: UUID) -> list[str]:
    """Return enabled predicate keys; persistence failures remain visible."""
    from app.models.knowledge_graph.entities import KgPredicateOntology  # noqa: WPS433

    rows = (
        db.query(KgPredicateOntology)
        .filter_by(tenant_id=tenant_id, is_enabled=True)
        .order_by(KgPredicateOntology.predicate.asc())
        .all()
    )
    out: list[str] = []
    seen: set[str] = set()
    for r in rows:
        key = r.predicate.strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def resolve_allowed_predicates(
    *,
    db: Session,
    tenant_id: UUID,
    fallback_default: Sequence[str],
    raw_override: str | None = None,
) -> list[str]:
    """
    Resolve the effective predicate allowlist for a tenant.

    Precedence:
    1) DB-enabled predicates (if any)
    2) raw_override (comma/newline separated)
    3) fallback_default
    """
    db_preds = load_enabled_predicates(db, tenant_id=tenant_id)
    if db_preds:
        return db_preds

    if raw_override:
        cleaned = [part for value in raw_override.replace("\n", ",").split(",") if (part := value.strip())]
        if cleaned:
            return cleaned

    return [part for value in fallback_default if (part := value.strip())]
