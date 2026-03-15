from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest


def test_build_regression_run_leaderboard_sorts_and_includes_config_hash(monkeypatch):  # noqa: ANN001
    from app.core.config import settings
    from app.services.regression_leaderboard import build_regression_run_leaderboard

    # Keep global toggles stable for fingerprinting in this unit test.
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "faiss", raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_TRGM_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "deterministic", raising=False)

    now = datetime.now(UTC)

    class _Run:
        def __init__(self, *, mrr: float, mode: str):  # noqa: ANN001
            self.id = uuid.uuid4()
            self.status = "completed"
            self.created_at = now
            self.finished_at = now
            self.summary = {"retrieval_mrr": mrr}
            self.params = {
                "rag_params": {
                    "top_k": 20,
                    "score_threshold": 0.0,
                    "retrieval_mode": mode,
                    "alpha": 0.6,
                    "enable_weight_rerank": True,
                    "vector_weight": 0.6,
                    "keyword_weight": 0.4,
                    "mmr_lambda": 0.7,
                    "enable_reranker": False,
                    "reranker_provider": "none",
                    "reranker_top_n": 20,
                }
            }

    low = _Run(mrr=0.1, mode="keyword")
    high = _Run(mrr=0.5, mode="vector")

    items = build_regression_run_leaderboard(runs=[low, high], metric_key="retrieval_mrr", limit=10)

    assert [x["run_id"] for x in items] == [str(high.id), str(low.id)]
    assert items[0]["metric_value"] == pytest.approx(0.5)
    assert items[0]["metric_key"] == "retrieval_mrr"
    assert items[0]["retrieval_config_hash"]


def test_regression_run_leaderboard_hash_changes_when_colbert_resource_cap_changes(monkeypatch):  # noqa: ANN001
    from app.core.config import settings
    from app.services.regression_leaderboard import build_regression_run_leaderboard

    monkeypatch.setattr(settings, "VECTOR_BACKEND", "faiss", raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_TRGM_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)

    now = datetime.now(UTC)

    class _Run:
        def __init__(self):  # noqa: ANN001
            self.id = uuid.uuid4()
            self.status = "completed"
            self.created_at = now
            self.finished_at = now
            self.summary = {"retrieval_mrr": 0.5}
            self.params = {
                "rag_params": {
                    "top_k": 20,
                    "score_threshold": 0.0,
                    "retrieval_mode": "vector",
                    "alpha": 0.6,
                    "enable_weight_rerank": True,
                    "vector_weight": 0.6,
                    "keyword_weight": 0.4,
                    "mmr_lambda": 0.7,
                    "enable_reranker": False,
                    "reranker_provider": "none",
                    "reranker_top_n": 20,
                }
            }

    run = _Run()

    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_MAX_DOCS", 100, raising=False)
    first = build_regression_run_leaderboard(runs=[run], metric_key="retrieval_mrr", limit=10)

    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_MAX_DOCS", 10, raising=False)
    second = build_regression_run_leaderboard(runs=[run], metric_key="retrieval_mrr", limit=10)

    assert first[0]["retrieval_config_hash"]
    assert second[0]["retrieval_config_hash"]
    assert first[0]["retrieval_config_hash"] != second[0]["retrieval_config_hash"]
