"""
RAG config template resolver.

Supports:
- explicit template_id selection
- latest active version by template_key
- A/B experiments with stable routing via ab_experiment_key + weights

This mirrors `app/services/prompt_resolver.py` but targets retrieval/rerank knobs.
"""


import hashlib
import json
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.rag_config_template import RagConfigTemplate
from app.rag.core.hashing import stable_hash

FeedbackRewardHook = Callable[
    [Session, UUID, str, Sequence[RagConfigTemplate]],
    dict[str, Any] | Sequence[Any] | None,
]


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


def build_adaptive_routing_reward_writeback(
    *,
    experiment_key: str | None,
    variant: str | None,
    strategy: str | None,
    decision: str | None,
    request_id: str | None,
    template_id: str | None = None,
    template_key: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "mimirq.rag_config_reward_writeback.v1",
        "experiment_key": str(experiment_key or "").strip()[:120] or "unknown",
        "variant": str(variant or "").strip()[:80] or "unknown",
        "strategy": str(strategy or "").strip()[:80] or "adaptive_epsilon_greedy",
        "decision": str(decision or "").strip()[:40] or "unknown",
        "request_id": str(request_id or "").strip()[:128],
    }
    tid = str(template_id or "").strip()
    if tid:
        payload["template_id"] = tid[:80]
    tkey = str(template_key or "").strip()
    if tkey:
        payload["template_key"] = tkey[:120]
    return payload


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _variant_key(variant: RagConfigTemplate) -> str:
    return str(getattr(variant, "ab_variant", None) or "").strip() or str(getattr(variant, "id", ""))


def _normalize_variant_weights(variants: Sequence[RagConfigTemplate]) -> tuple[list[float], float]:
    weights: list[float] = []
    total = 0.0
    for variant in variants:
        weight = float(getattr(variant, "ab_weight", 1.0) or 0.0)
        if weight < 0:
            weight = 0.0
        weights.append(weight)
        total += weight
    if total <= 0:
        weights = [1.0 for _ in variants]
        total = float(len(variants))
    return weights, total


def _weighted_pick(
    *,
    variants: Sequence[RagConfigTemplate],
    weights: Sequence[float],
    total_weight: float,
    seed: str,
) -> RagConfigTemplate:
    r = _stable_unit_interval(seed) * float(total_weight or 1.0)
    acc = 0.0
    for variant, weight in zip(variants, weights, strict=False):
        acc += float(weight or 0.0)
        if r <= acc:
            return variant
    return variants[-1]


def _coerce_reward(value: Any) -> float | None:
    rating = _as_float(value)
    if rating is None:
        return None
    # Map a typical 1..5 rating to [-1, 1] while staying tolerant for out-of-range values.
    reward = (rating - 3.0) / 2.0
    if reward > 1.0:
        reward = 1.0
    if reward < -1.0:
        reward = -1.0
    return reward


def aggregate_feedback_rewards(
    feedback_rows: Sequence[Any] | None,
    *,
    variant_field: str = "ab_variant",
    rating_field: str = "rating",
    reward_field: str = "reward",
) -> dict[str, Any]:
    bucket: dict[str, dict[str, float]] = {}
    total_feedback = 0

    for row in (feedback_rows or []):
        if isinstance(row, dict):
            variant_raw = row.get(variant_field)
            rating = _as_float(row.get(rating_field))
            reward = _as_float(row.get(reward_field))
        else:
            variant_raw = getattr(row, variant_field, None)
            rating = _as_float(getattr(row, rating_field, None))
            reward = _as_float(getattr(row, reward_field, None))

        variant = str(variant_raw or "").strip()
        if not variant:
            continue
        if reward is None:
            reward = _coerce_reward(rating)
        if reward is None:
            continue

        stats = bucket.setdefault(variant, {"count": 0.0, "reward_sum": 0.0, "rating_sum": 0.0, "rating_count": 0.0})
        stats["count"] += 1.0
        stats["reward_sum"] += float(reward)
        if rating is not None:
            stats["rating_sum"] += float(rating)
            stats["rating_count"] += 1.0
        total_feedback += 1

    variants: dict[str, dict[str, Any]] = {}
    for key, stats in bucket.items():
        count = max(1.0, float(stats.get("count") or 1.0))
        rating_count = float(stats.get("rating_count") or 0.0)
        avg_rating = float(stats.get("rating_sum") or 0.0) / rating_count if rating_count > 0 else None
        variants[key] = {
            "count": int(count),
            "avg_reward": round(float(stats.get("reward_sum") or 0.0) / count, 4),
            "avg_rating": (round(float(avg_rating), 4) if avg_rating is not None else None),
        }

    return {
        "schema": "mimirq.rag_config_reward_snapshot.v1",
        "total_feedback": int(total_feedback),
        "variants": variants,
    }


def _normalize_reward_snapshot(
    *,
    variants: Sequence[RagConfigTemplate],
    snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    raw = snapshot if isinstance(snapshot, dict) else {}
    raw_variants = raw.get("variants") if isinstance(raw.get("variants"), dict) else {}
    normalized_variants: dict[str, dict[str, Any]] = {}
    for variant in variants:
        v_key = _variant_key(variant)
        candidate = raw_variants.get(v_key)
        if candidate is None:
            candidate = raw_variants.get(str(getattr(variant, "id", "")))
        info = candidate if isinstance(candidate, dict) else {}

        reward = _as_float(info.get("avg_reward"))
        if reward is None:
            reward = _as_float(info.get("reward"))
        if reward is None:
            reward = _coerce_reward(info.get("avg_rating"))
        if reward is None:
            reward = 0.0

        normalized_variants[v_key] = {
            "count": int(info.get("count") or 0),
            "avg_reward": round(float(reward), 4),
            "avg_rating": _as_float(info.get("avg_rating")),
        }

    return {
        "schema": "mimirq.rag_config_reward_snapshot.v1",
        "total_feedback": int(raw.get("total_feedback") or 0),
        "variants": normalized_variants,
    }


def _pick_highest_reward_variant(
    *,
    variants: Sequence[RagConfigTemplate],
    reward_snapshot: dict[str, Any],
    seed: str,
) -> RagConfigTemplate:
    reward_map = reward_snapshot.get("variants") if isinstance(reward_snapshot.get("variants"), dict) else {}
    scored: list[tuple[RagConfigTemplate, float]] = []
    for variant in variants:
        info = reward_map.get(_variant_key(variant))
        score = _as_float((info or {}).get("avg_reward")) if isinstance(info, dict) else None
        scored.append((variant, float(score or 0.0)))

    max_reward = max(score for _variant, score in scored)
    candidates = [variant for variant, score in scored if abs(score - max_reward) <= 1e-12]
    if len(candidates) == 1:
        return candidates[0]

    ranked = sorted(candidates, key=lambda x: _variant_key(x))
    idx = int(_stable_unit_interval(f"{seed}:exploit_choice") * len(ranked))
    if idx >= len(ranked):
        idx = len(ranked) - 1
    return ranked[idx]


def _resolver_debug_payload(
    *,
    strategy: str,
    decision: str,
    chosen: RagConfigTemplate | None,
    epsilon: float | None = None,
    reward_snapshot: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    debug: dict[str, Any] = {
        "strategy": strategy,
        "epsilon": epsilon,
        "decision": decision,
        "chosen_variant": _variant_key(chosen) if chosen is not None else None,
        "reward_snapshot": reward_snapshot,
    }
    if weights is not None:
        debug["weights"] = weights
    return debug


def _return_with_optional_debug(
    *,
    chosen: RagConfigTemplate | None,
    debug: dict[str, Any] | None,
    return_debug_metadata: bool,
) -> RagConfigTemplate | None | tuple[RagConfigTemplate | None, dict[str, Any] | None]:
    return (chosen, debug) if return_debug_metadata else chosen


def _resolve_experiment_variants(
    *,
    db: Session,
    tenant_id: UUID,
    query: Any,
    ab_experiment_key: str,
    ab_user_key: str | None,
    routing_mode: str,
    adaptive_epsilon: float,
    feedback_reward_snapshot: dict[str, Any] | None,
    feedback_reward_hook: FeedbackRewardHook | None,
    return_debug_metadata: bool,
) -> RagConfigTemplate | None | tuple[RagConfigTemplate | None, dict[str, Any] | None]:
    exp = str(ab_experiment_key or "").strip()
    if not exp:
        return _return_with_optional_debug(chosen=None, debug=None, return_debug_metadata=return_debug_metadata)

    variants = (
        query.filter(RagConfigTemplate.ab_experiment_key == exp)
        .order_by(RagConfigTemplate.ab_variant.asc().nullslast(), RagConfigTemplate.updated_at.desc())
        .all()
    )
    if not variants:
        return _return_with_optional_debug(chosen=None, debug=None, return_debug_metadata=return_debug_metadata)

    if len(variants) == 1:
        single = variants[0]
        return _return_with_optional_debug(
            chosen=single,
            debug=_resolver_debug_payload(
                strategy="weighted",
                epsilon=None,
                decision="single_variant",
                chosen=single,
                reward_snapshot=None,
                weights={_variant_key(single): 1.0},
            ),
            return_debug_metadata=return_debug_metadata,
        )

    weights, total = _normalize_variant_weights(variants)
    seed = f"{exp}:{ab_user_key or ''}"
    weighted_choice = _weighted_pick(
        variants=variants,
        weights=weights,
        total_weight=total,
        seed=f"{seed}:weighted",
    )
    weights_map = {str(_variant_key(v)): round(float(w), 4) for v, w in zip(variants, weights, strict=False)}

    routing = str(routing_mode or "weighted").strip().lower()
    if routing in {"adaptive_epsilon_greedy", "epsilon_greedy"}:
        routing = "adaptive"
    if routing != "adaptive":
        return _return_with_optional_debug(
            chosen=weighted_choice,
            debug=_resolver_debug_payload(
                strategy="weighted",
                epsilon=None,
                decision="weighted",
                chosen=weighted_choice,
                reward_snapshot=None,
                weights=weights_map,
            ),
            return_debug_metadata=return_debug_metadata,
        )

    epsilon = _as_float(adaptive_epsilon)
    epsilon = min(1.0, max(0.0, float(0.1 if epsilon is None else epsilon)))
    reward_snapshot = feedback_reward_snapshot if isinstance(feedback_reward_snapshot, dict) else None
    if reward_snapshot is None and feedback_reward_hook is not None:
        try:
            raw_snapshot = feedback_reward_hook(db, tenant_id, exp, variants)
            if isinstance(raw_snapshot, dict):
                reward_snapshot = dict(raw_snapshot)
            elif isinstance(raw_snapshot, Sequence):
                reward_snapshot = aggregate_feedback_rewards(raw_snapshot)
        except Exception:
            reward_snapshot = None

    normalized_snapshot = _normalize_reward_snapshot(variants=variants, snapshot=reward_snapshot)
    explore = _stable_unit_interval(f"{seed}:adaptive:explore") < epsilon
    chosen = weighted_choice if explore else _pick_highest_reward_variant(
        variants=variants,
        reward_snapshot=normalized_snapshot,
        seed=seed,
    )
    decision = "explore" if explore else "exploit"
    return _return_with_optional_debug(
        chosen=chosen,
        debug=_resolver_debug_payload(
            strategy="adaptive_epsilon_greedy",
            epsilon=round(float(epsilon), 4),
            decision=decision,
            chosen=chosen,
            reward_snapshot=normalized_snapshot,
            weights=weights_map,
        ),
        return_debug_metadata=return_debug_metadata,
    )


def resolve_rag_config_template(
    *,
    db: Session,
    tenant_id: UUID,
    rag_config_template_id: UUID | None = None,
    template_key: str | None = None,
    ab_experiment_key: str | None = None,
    ab_user_key: str | None = None,
    routing_mode: str = "weighted",
    adaptive_epsilon: float = 0.1,
    feedback_reward_snapshot: dict[str, Any] | None = None,
    feedback_reward_hook: FeedbackRewardHook | None = None,
    return_debug_metadata: bool = False,
) -> RagConfigTemplate | None | tuple[RagConfigTemplate | None, dict[str, Any] | None]:
    """
    Resolve the final RagConfigTemplate to use (returns ORM object).

    Priority:
    1) rag_config_template_id
    2) template_key (is_active with highest version)
    3) ab_experiment_key (active variants, stable routing by ab_weight)
    """
    if rag_config_template_id:
        chosen = (
            db.query(RagConfigTemplate)
            .filter(
                RagConfigTemplate.id == rag_config_template_id,
                RagConfigTemplate.tenant_id == tenant_id,
                RagConfigTemplate.is_active == True,  # noqa: E712
            )
            .first()
        )
        return _return_with_optional_debug(
            chosen=chosen,
            debug=_resolver_debug_payload(
                strategy="explicit_template_id",
                epsilon=None,
                decision="explicit",
                chosen=chosen,
                reward_snapshot=None,
            ),
            return_debug_metadata=return_debug_metadata,
        )

    query = db.query(RagConfigTemplate).filter(
        RagConfigTemplate.tenant_id == tenant_id,
        RagConfigTemplate.is_active == True,  # noqa: E712
    )

    if template_key:
        key = str(template_key or "").strip()
        if key:
            chosen = (
                query.filter(RagConfigTemplate.template_key == key)
                .order_by(RagConfigTemplate.version.desc(), RagConfigTemplate.updated_at.desc())
                .first()
            )
            return _return_with_optional_debug(
                chosen=chosen,
                debug=_resolver_debug_payload(
                    strategy="template_key_latest",
                    epsilon=None,
                    decision="latest",
                    chosen=chosen,
                    reward_snapshot=None,
                ),
                return_debug_metadata=return_debug_metadata,
            )

    if ab_experiment_key:
        return _resolve_experiment_variants(
            db=db,
            tenant_id=tenant_id,
            query=query,
            ab_experiment_key=ab_experiment_key,
            ab_user_key=ab_user_key,
            routing_mode=routing_mode,
            adaptive_epsilon=adaptive_epsilon,
            feedback_reward_snapshot=feedback_reward_snapshot,
            feedback_reward_hook=feedback_reward_hook,
            return_debug_metadata=return_debug_metadata,
        )

    return _return_with_optional_debug(chosen=None, debug=None, return_debug_metadata=return_debug_metadata)


__all__ = [
    "aggregate_feedback_rewards",
    "build_adaptive_routing_reward_writeback",
    "build_rag_config_patch_hash",
    "resolve_rag_config_template",
]
