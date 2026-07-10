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
    """Return enabled predicate keys from kg_predicate_ontology (best-effort)."""
    try:
        from app.rag.kg.models import KgPredicateOntology  # noqa: WPS433

        rows = (
            db.query(KgPredicateOntology)
            .filter_by(tenant_id=tenant_id, is_enabled=True)
            .order_by(KgPredicateOntology.predicate.asc())
            .all()
        )
        out: list[str] = []
        seen: set[str] = set()
        for r in rows:
            key = str(getattr(r, "predicate", "") or "").strip()
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out
    except Exception:
        # Must be fail-open to preserve backward-compatible extraction behavior.
        return []


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
        return list(db_preds)

    raw = str(raw_override or "").strip()
    if raw:
        parts = [p.strip() for p in raw.replace("\r\n", "\n").split("\n") for p in p.split(",")]
        cleaned = [p for p in (str(x or "").strip() for x in parts) if p]
        if cleaned:
            return cleaned

    return [str(p).strip() for p in (fallback_default or []) if str(p).strip()]

