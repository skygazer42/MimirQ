from __future__ import annotations

from prometheus_client import generate_latest


def test_build_router_layers_combines_entity_intent_and_composite() -> None:
    from app.rag.policy.router_layers import build_router_layers

    out = build_router_layers(
        query="Compare ACME Holdings and ACME onboarding flow screenshot",
        entity_candidates=["ACME", "ACME Holdings"],
    )

    assert out["schema"] == "mimirq.router_layers.v1"
    entity = out["entity"] or {}
    intent = out["intent"] or {}
    composite = out["composite"] or {}

    assert entity["decision"] == "partition_keys"
    assert entity["partition_keys"] == ["ACME Holdings", "ACME"]
    assert intent["decision"] in {"general", "howto", "faq", "api", "log"}
    assert composite["decision"] == "compare"
    assert "compare_pattern" in list(composite.get("reason_codes") or [])


def test_observe_router_layers_emits_low_cardinality_metrics(monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import settings
    from app.rag.policy.router_layers import build_router_layers
    from app.services.router_prometheus_metrics import observe_router_layers

    monkeypatch.setattr(settings, "PROMETHEUS_ENABLED", True, raising=False)

    layers = build_router_layers(
        query="Compare ACME Holdings and ACME",
        entity_candidates=["ACME", "ACME Holdings"],
    )
    observe_router_layers(layers)

    text = generate_latest().decode("utf-8", errors="ignore")
    assert 'rag_router_decision_total{decision="partition_keys",level="entity",used="true"}' in text
    assert 'rag_router_decision_total{decision="compare",level="composite",used="true"}' in text
