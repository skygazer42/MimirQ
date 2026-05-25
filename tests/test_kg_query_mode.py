from __future__ import annotations

import uuid

import pytest


def test_classify_kg_query_mode_detects_drift() -> None:
    from app.rag.kg.search.query_mode import classify_kg_query_mode

    out = classify_kg_query_mode(query="Compare year over year revenue drift by region")
    assert out["mode"] == "drift"
    assert "drift_pattern" in list(out.get("reason_codes") or [])


def test_classify_kg_query_mode_detects_local_row_focus() -> None:
    from app.rag.kg.search.query_mode import classify_kg_query_mode

    out = classify_kg_query_mode(
        query='which row has id=42 with "APAC" region',
        document_ids=[str(uuid.uuid4())],
    )
    assert out["mode"] == "local"


def test_classify_kg_query_mode_treats_dataset_factoid_as_local() -> None:
    from app.rag.kg.search.query_mode import classify_kg_query_mode

    out = classify_kg_query_mode(
        query="Which survey reviews graph neural networks including graph convolution and graph attention networks?",
        dataset_id=uuid.uuid4(),
    )

    assert out["mode"] == "local"
    assert out["confidence"] == "medium"
    assert "dataset_factoid_scope" in list(out.get("reason_codes") or [])


def test_build_mode_aware_recall_overrides_shapes_local_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.kg.search.query_mode import build_mode_aware_recall_overrides

    monkeypatch.setattr(settings, "KG_SEARCH_QUERY_MODE_LOCAL_MAX_EVENTS", 20, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_QUERY_MODE_LOCAL_ENTITY_WEIGHT_BONUS", 0.1, raising=False)

    shaped = build_mode_aware_recall_overrides(
        mode="local",
        max_events=100,
        max_entities=50,
        final_entity_count=30,
        entity_weight_threshold=0.05,
    )
    assert int(shaped["max_events"]) == 20
    assert float(shaped["entity_weight_threshold"]) > 0.05


def test_build_mode_aware_recall_overrides_keeps_low_confidence_global_light(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag.kg.search.query_mode import build_mode_aware_recall_overrides

    monkeypatch.setattr(settings, "KG_SEARCH_QUERY_MODE_GLOBAL_MIN_EVENTS", 120, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_QUERY_MODE_LOW_CONFIDENCE_GLOBAL_MAX_EVENTS", 50, raising=False)

    shaped = build_mode_aware_recall_overrides(
        mode="global",
        max_events=80,
        max_entities=30,
        final_entity_count=20,
        entity_weight_threshold=0.05,
        query_mode_confidence="low",
        query_mode_reason_codes=["dataset_scope_no_doc_ids"],
    )

    assert int(shaped["max_events"]) == 50
    assert int(shaped["max_entities"]) == 30
    assert "low_confidence_global_budget" in list(shaped.get("reason_codes") or [])


def test_build_mode_aware_recall_overrides_keeps_explicit_global_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag.kg.search.query_mode import build_mode_aware_recall_overrides

    monkeypatch.setattr(settings, "KG_SEARCH_QUERY_MODE_GLOBAL_MIN_EVENTS", 120, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_QUERY_MODE_LOW_CONFIDENCE_GLOBAL_MAX_EVENTS", 50, raising=False)

    shaped = build_mode_aware_recall_overrides(
        mode="global",
        max_events=80,
        max_entities=30,
        final_entity_count=20,
        entity_weight_threshold=0.05,
        query_mode_confidence="medium",
        query_mode_reason_codes=["global_pattern"],
    )

    assert int(shaped["max_events"]) == 120
    assert int(shaped["max_entities"]) == 40
    assert "global_coverage_budget" in list(shaped.get("reason_codes") or [])


def test_search_config_accepts_query_mode_fields() -> None:
    from app.rag.kg.search.config import SearchConfig

    cfg = SearchConfig(
        query="overall trend",
        query_mode="global",
        query_mode_reason_codes=["global_pattern"],
        query_mode_confidence="medium",
    )
    assert cfg.query_mode == "global"
    assert cfg.query_mode_reason_codes == ["global_pattern"]
    assert cfg.query_mode_confidence == "medium"
