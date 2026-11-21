from prometheus_client import Counter

from app.infrastructure.config import settings

RAG_INPUT_GUARD_TOTAL = Counter(
    "rag_input_guard_total",
    "Total input guard decisions",
    ["action", "rule"],
)


def observe_input_guard(*, action: str, matched_rules: list[str]) -> None:
    if not bool(settings.PROMETHEUS_ENABLED):
        return
    labels = list(matched_rules or ["none"])
    action_label = action.strip().lower() or "allow"
    for rule in labels[:8]:
        RAG_INPUT_GUARD_TOTAL.labels(
            action=action_label,
            rule=(rule.strip().lower() or "none"),
        ).inc()


__all__ = ["observe_input_guard"]
