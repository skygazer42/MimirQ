"""
RAG config template resolver.

Supports:
- explicit template_id selection
- latest active version by template_key
- A/B experiments with stable routing via ab_experiment_key + weights

This mirrors `app/services/prompt_resolver.py` but targets retrieval/rerank knobs.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.rag_config_template import RagConfigTemplate
from app.rag.core.hashing import stable_hash


def _stable_unit_interval(seed: str) -> float:
    """Map a seed to a stable pseudo-random number in [0, 1) for A/B routing."""
    raw = hashlib.sha256(seed.encode("utf-8")).digest()
    num = int.from_bytes(raw[:8], "big", signed=False)
    return (num % 1_000_000) / 1_000_000.0


def build_rag_config_patch_hash(patch: Any) -> str:
    """
    Stable short hash for a RAG config patch (PII-safe).

    Notes:
    - The patch is expected to be a dict with only low-cardinality knob values.
    - We strip null/empty keys best-effort to keep hashes stable.
    """
    obj = patch if isinstance(patch, dict) else {}
    cleaned: dict[str, Any] = {}
    for k, v in obj.items():
        key = str(k or "").strip()
        if not key:
            continue
        if v is None:
            continue
        cleaned[key] = v
    payload = json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return stable_hash(payload, length=16)


def resolve_rag_config_template(
    *,
    db: Session,
    tenant_id: UUID,
    rag_config_template_id: Optional[UUID] = None,
    template_key: Optional[str] = None,
    ab_experiment_key: Optional[str] = None,
    ab_user_key: Optional[str] = None,
) -> Optional[RagConfigTemplate]:
    """
    Resolve the final RagConfigTemplate to use (returns ORM object).

    Priority:
    1) rag_config_template_id
    2) template_key (is_active with highest version)
    3) ab_experiment_key (active variants, stable routing by ab_weight)
    """
    if rag_config_template_id:
        return (
            db.query(RagConfigTemplate)
            .filter(
                RagConfigTemplate.id == rag_config_template_id,
                RagConfigTemplate.tenant_id == tenant_id,
                RagConfigTemplate.is_active == True,  # noqa: E712
            )
            .first()
        )

    query = db.query(RagConfigTemplate).filter(
        RagConfigTemplate.tenant_id == tenant_id,
        RagConfigTemplate.is_active == True,  # noqa: E712
    )

    if template_key:
        key = str(template_key or "").strip()
        if key:
            return (
                query.filter(RagConfigTemplate.template_key == key)
                .order_by(RagConfigTemplate.version.desc(), RagConfigTemplate.updated_at.desc())
                .first()
            )

    if ab_experiment_key:
        exp = str(ab_experiment_key or "").strip()
        if not exp:
            return None

        variants = (
            query.filter(RagConfigTemplate.ab_experiment_key == exp)
            .order_by(RagConfigTemplate.ab_variant.asc().nullslast(), RagConfigTemplate.updated_at.desc())
            .all()
        )
        if not variants:
            return None
        if len(variants) == 1:
            return variants[0]

        weights: list[float] = []
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

        seed = f"{exp}:{ab_user_key or ''}"
        r = _stable_unit_interval(seed) * total
        acc = 0.0
        for v, w in zip(variants, weights, strict=False):
            acc += w
            if r <= acc:
                return v
        return variants[-1]

    return None


__all__ = ["build_rag_config_patch_hash", "resolve_rag_config_template"]

