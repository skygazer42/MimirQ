"""
PromptTemplate resolver that supports:
- explicit prompt_template_id selection
- A/B experiments with stable routing via ab_experiment_key + weights

Used by the chat/RAG engine to decide which template to use at runtime and
persist the choice into message_metadata for evaluation loops (A/B comparisons,
user feedback correlation, regression datasets, and more).
"""

import hashlib
from collections.abc import Sequence
from typing import TYPE_CHECKING, TypeVar
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.templates.versions import PromptTemplate

if TYPE_CHECKING:
    from sqlalchemy.orm import Query

Variant = TypeVar("Variant")


def _stable_unit_interval(seed: str) -> float:
    """Map a seed to a stable pseudo-random number in [0, 1) for A/B routing."""
    raw = hashlib.sha256(seed.encode("utf-8")).digest()
    num = int.from_bytes(raw[:8], "big", signed=False)
    return (num % 1_000_000) / 1_000_000.0


def pick_weighted_variant(variants: Sequence[Variant], weights: Sequence[float], *, sample: float) -> Variant:
    """Select from positive weights using a sample scaled to the total weight."""
    cumulative = 0.0
    for variant, weight in zip(variants, weights, strict=False):
        cumulative += weight
        if weight > 0 and sample <= cumulative:
            return variant
    return variants[-1]


def _active_prompt_template_query(*, db: Session, tenant_id: UUID) -> "Query[PromptTemplate]":
    return db.query(PromptTemplate).filter(
        PromptTemplate.tenant_id == tenant_id,
        PromptTemplate.is_active == True,  # noqa: E712
    )


def _weighted_variants(variants: list[PromptTemplate]) -> tuple[list[float], float]:
    weights: list[float] = []
    total = 0.0
    for variant in variants:
        weight = variant.ab_weight or 0.0
        if weight < 0:
            weight = 0.0
        weights.append(weight)
        total += weight
    if total > 0:
        return weights, total
    return [1.0] * len(variants), float(len(variants))


def _resolve_ab_variant(
    *,
    query: "Query[PromptTemplate]",
    ab_experiment_key: str,
    ab_user_key: str | None,
) -> PromptTemplate | None:
    variants = (
        query.filter(PromptTemplate.ab_experiment_key == ab_experiment_key)
        .order_by(PromptTemplate.ab_variant.asc().nullslast(), PromptTemplate.updated_at.desc())
        .all()
    )
    if not variants:
        return None
    if len(variants) == 1:
        return variants[0]

    weights, total = _weighted_variants(variants)
    sample = _stable_unit_interval(f"{ab_experiment_key}:{ab_user_key or ''}") * total
    return pick_weighted_variant(variants, weights, sample=sample)


def resolve_prompt_template(
    *,
    db: Session,
    tenant_id: UUID,
    prompt_template_id: UUID | None = None,
    template_key: str | None = None,
    ab_experiment_key: str | None,
    ab_user_key: str | None,
) -> PromptTemplate | None:
    """
    Resolve the final PromptTemplate to use (returns ORM object).

    Priority:
    1) prompt_template_id
    2) template_key (is_active with highest version)
    3) ab_experiment_key (active variants, stable routing by ab_weight)
    """
    if prompt_template_id:
        return (
            _active_prompt_template_query(db=db, tenant_id=tenant_id)
            .filter(
                PromptTemplate.id == prompt_template_id,
            )
            .first()
        )

    query = _active_prompt_template_query(db=db, tenant_id=tenant_id)

    if template_key:
        return query.filter(PromptTemplate.template_key == template_key).order_by(PromptTemplate.version.desc()).first()

    if ab_experiment_key:
        return _resolve_ab_variant(query=query, ab_experiment_key=ab_experiment_key, ab_user_key=ab_user_key)

    return None
