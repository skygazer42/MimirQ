from __future__ import annotations

from pathlib import Path


def test_leaderboard_endpoint_is_registered():
    # Keep this test lightweight: do not import FastAPI modules that pull heavy ML deps.
    text = Path("app/api/v1/evaluations.py").read_text(encoding="utf-8")
    assert '@router.get("/ragas/regression/runs/leaderboard"' in text


def test_leaderboard_schema_exposes_retrieval_config_hash_field():
    from app.api.schemas.regression import RagasRegressionRunLeaderboardItem

    assert "retrieval_config_hash" in RagasRegressionRunLeaderboardItem.model_fields

