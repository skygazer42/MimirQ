from __future__ import annotations

import json
from pathlib import Path

from app.rag.policy.intent_router_model import load_intent_router_model


def _model_payload() -> dict:
    return {
        "schema": "mimirq.intent_router_model.v1",
        "version": 1,
        "rules": [
            {
                "rule_id": "r1",
                "tokens": ["faq", "howto"],
                "min_match": 1,
                "confidence": 0.8,
                "weight": 1.0,
                "overrides": {
                    "retrieval_mode": "hybrid",
                },
            }
        ],
    }


def test_load_intent_router_model_accepts_relative_path_under_cwd(tmp_path: Path, monkeypatch) -> None:
    model_path = tmp_path / "artifacts" / "intent_router_model.v1.json"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(_model_payload(), ensure_ascii=False), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    loaded = load_intent_router_model("artifacts/intent_router_model.v1.json")
    assert isinstance(loaded, dict)
    assert loaded.get("schema") == "mimirq.intent_router_model.v1"
    assert isinstance(loaded.get("rules"), list)


def test_load_intent_router_model_rejects_absolute_path_outside_cwd(tmp_path: Path, monkeypatch) -> None:
    outside_model = tmp_path.parent / f"{tmp_path.name}-intent-router-model.json"
    outside_model.write_text(json.dumps(_model_payload(), ensure_ascii=False), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert load_intent_router_model(str(outside_model)) is None
