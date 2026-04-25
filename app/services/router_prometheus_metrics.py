from __future__ import annotations

from prometheus_client import Counter

from app.core.config import settings

ROUTER_DECISION_TOTAL = Counter(
    "rag_router_decision_total",
    "Deterministic router layer decisions",
    ["level", "decision", "used"],
)


def observe_router_layers(layers: dict | None) -> None:
    if not bool(getattr(settings, "PROMETHEUS_ENABLED", False)):
        return
    payload = layers if isinstance(layers, dict) else {}
    for level in ("entity", "intent", "composite"):
        item = payload.get(level) if isinstance(payload.get(level), dict) else {}
        decision = str(item.get("decision") or "unknown").strip().lower() or "unknown"
        used = str(bool(item.get("used") or False)).lower()
        ROUTER_DECISION_TOTAL.labels(level=level, decision=decision, used=used).inc()


__all__ = ["observe_router_layers"]
