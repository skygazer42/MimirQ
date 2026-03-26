from __future__ import annotations

from app.core.config import settings

try:
    from prometheus_client import Counter
except Exception:  # pragma: no cover - optional dependency path
    Counter = None

if Counter is not None:
    RAG_INPUT_GUARD_TOTAL = Counter(
        "rag_input_guard_total",
        "Total input guard decisions",
        ["action", "rule"],
    )
else:  # pragma: no cover - exercised only when prometheus import is unavailable
    RAG_INPUT_GUARD_TOTAL = None


def observe_input_guard(*, action: str, matched_rules: list[str]) -> None:
    if not bool(getattr(settings, "PROMETHEUS_ENABLED", False)):
        return
    if RAG_INPUT_GUARD_TOTAL is None:
        return

    labels = list(matched_rules or ["none"])
    for rule in labels[:8]:
        RAG_INPUT_GUARD_TOTAL.labels(
            action=(str(action or "").strip().lower() or "allow"),
            rule=(str(rule or "").strip().lower() or "none"),
        ).inc()


__all__ = ["observe_input_guard"]
