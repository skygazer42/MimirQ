"""
PromptTemplate resolver that supports:
- explicit prompt_template_id selection
- A/B experiments with stable routing via ab_experiment_key + weights

Used by the chat/RAG engine to decide which template to use at runtime and
persist the choice into message_metadata for evaluation loops (A/B comparisons,
user feedback correlation, regression datasets, and more).
"""


import hashlib
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.prompt_template import PromptTemplate


def _stable_unit_interval(seed: str) -> float:
    """Map a seed to a stable pseudo-random number in [0, 1) for A/B routing."""
    raw = hashlib.sha256(seed.encode("utf-8")).digest()
    num = int.from_bytes(raw[:8], "big", signed=False)
    return (num % 1_000_000) / 1_000_000.0


def resolve_prompt_template(
    *,
    db: Session,
    tenant_id: UUID,
    prompt_template_id: Optional[UUID] = None,
    template_key: Optional[str] = None,
    ab_experiment_key: Optional[str] = None,
    ab_user_key: Optional[str] = None,
) -> Optional[PromptTemplate]:
    """
    Resolve the final PromptTemplate to use (returns ORM object).

    Priority:
    1) prompt_template_id
    2) template_key (is_active with highest version)
    3) ab_experiment_key (active variants, stable routing by ab_weight)
    """
    if prompt_template_id:
        return (
            db.query(PromptTemplate)
            .filter(
                PromptTemplate.id == prompt_template_id,
                PromptTemplate.tenant_id == tenant_id,
                PromptTemplate.is_active == True,  # noqa: E712
            )
            .first()
        )

    query = db.query(PromptTemplate).filter(
        PromptTemplate.tenant_id == tenant_id,
        PromptTemplate.is_active == True,  # noqa: E712
    )

    if template_key:
        return (
            query.filter(PromptTemplate.template_key == template_key)
            .order_by(PromptTemplate.version.desc())
            .first()
        )

    if ab_experiment_key:
        variants = (
            query.filter(PromptTemplate.ab_experiment_key == ab_experiment_key)
            .order_by(PromptTemplate.ab_variant.asc().nullslast(), PromptTemplate.updated_at.desc())
            .all()
        )
        if not variants:
            return None
        if len(variants) == 1:
            return variants[0]

        weights = []
        total = 0.0
        for v in variants:
            w = float(getattr(v, "ab_weight", 1.0) or 0.0)
            if w < 0:
                w = 0.0
            weights.append(w)
            total += w
        if total <= 0:
            weights = [1.0 for _ in variants]
            total = float(len(variants))

        seed = f"{ab_experiment_key}:{ab_user_key or ''}"
        r = _stable_unit_interval(seed) * total
        acc = 0.0
        for v, w in zip(variants, weights, strict=False):
            acc += w
            if r <= acc:
                return v
        return variants[-1]

    return None
