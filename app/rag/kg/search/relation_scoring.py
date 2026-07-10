"""
Relation expansion scoring helpers.

KG extraction persists relations as normalized predicates (snake_case) with an LLM confidence.
During KG search, we treat different predicates as having different usefulness for recall:
- Identity / alias edges are high-signal.
- Structural edges (is_a, part_of, depends_on, uses) are usually better than generic ones.
- "unknown" predicate edges are ignored for expansion.

This keeps relation-driven expansion helpful for RAG recall while limiting query drift.
"""


from dataclasses import dataclass


@dataclass(frozen=True)
class PredicatePrior:
    """
    Predicate weighting priors for relation-driven expansion.

    - weight: overall usefulness multiplier (0..2-ish)
    - forward/reverse: directionality multiplier relative to stored subject->object direction.
      For many predicates we treat both directions as useful but not equal.
    """

    weight: float
    forward: float = 1.0
    reverse: float = 1.0


_DEFAULT_PREDICATE_PRIORS: dict[str, PredicatePrior] = {
    # Identity / alias (strong).
    "alias_of": PredicatePrior(weight=1.2, forward=1.0, reverse=1.0),
    "same_as": PredicatePrior(weight=1.2, forward=1.0, reverse=1.0),
    # Ontology-ish structure.
    "is_a": PredicatePrior(weight=0.9, forward=1.0, reverse=0.7),
    "part_of": PredicatePrior(weight=0.9, forward=1.0, reverse=0.8),
    "has_part": PredicatePrior(weight=0.85, forward=1.0, reverse=0.85),
    "member_of": PredicatePrior(weight=0.85, forward=1.0, reverse=0.8),
    "located_in": PredicatePrior(weight=0.8, forward=1.0, reverse=0.7),
    # Organizations / reporting.
    "works_for": PredicatePrior(weight=0.8, forward=1.0, reverse=0.7),
    "reports_to": PredicatePrior(weight=0.75, forward=1.0, reverse=0.6),
    # Ownership / authorship.
    "owns": PredicatePrior(weight=0.75, forward=1.0, reverse=0.85),
    "owned_by": PredicatePrior(weight=0.75, forward=1.0, reverse=0.85),
    "created_by": PredicatePrior(weight=0.75, forward=1.0, reverse=0.8),
    "authored_by": PredicatePrior(weight=0.75, forward=1.0, reverse=0.8),
    # Software / systems.
    "uses": PredicatePrior(weight=0.85, forward=1.0, reverse=0.75),
    "depends_on": PredicatePrior(weight=0.9, forward=1.0, reverse=0.75),
    # SkillNet-style taxonomy / composition.
    # - "belong_to": Skill -> SkillTag / SkillCategory edges (reverse direction is often more useful for recall).
    "belong_to": PredicatePrior(weight=0.85, forward=0.6, reverse=1.0),
    # - "compose_with": Skill -> Skill edges indicating composability (symmetric).
    "compose_with": PredicatePrior(weight=0.65, forward=1.0, reverse=1.0),
    "implements": PredicatePrior(weight=0.8, forward=1.0, reverse=0.7),
    "supports": PredicatePrior(weight=0.8, forward=1.0, reverse=0.7),
    # Causal-ish edges (directional).
    "causes": PredicatePrior(weight=0.75, forward=1.0, reverse=0.5),
    "affects": PredicatePrior(weight=0.7, forward=1.0, reverse=0.6),
    "treats": PredicatePrior(weight=0.7, forward=1.0, reverse=0.5),
    # Symmetric-ish / generic.
    "works_with": PredicatePrior(weight=0.65, forward=1.0, reverse=1.0),
    "related_to": PredicatePrior(weight=0.55, forward=1.0, reverse=1.0),
}


def relation_multiplier(predicate: str, *, from_is_subject: bool) -> float:
    """
    Return a multiplier for relation-based expansion.

    - 0.0 means "do not expand this edge" (e.g., unknown predicate).
    - Fallback (unknown but non-empty) is intentionally modest to reduce drift.
    """
    pred = (predicate or "").strip()
    if not pred:
        return 0.0

    key = pred.casefold()
    if key == "unknown":
        return 0.0

    prior = _DEFAULT_PREDICATE_PRIORS.get(key)
    if prior is None:
        return 0.5

    direction = float(prior.forward if from_is_subject else prior.reverse)
    return max(0.0, float(prior.weight) * direction)


__all__ = ["PredicatePrior", "relation_multiplier"]
