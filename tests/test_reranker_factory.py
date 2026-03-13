from __future__ import annotations

import pytest


def test_colbert_factory_falls_back_to_deterministic_when_hf_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag.reranker.factory import get_reranker

    monkeypatch.setattr(settings, "COLBERT_RERANK_PROVIDER", "hf", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_MODEL_NAME", "", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_HEALTHCHECK_STRICT", False, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_WARMUP_ENABLED", False, raising=False)

    inst = get_reranker("colbert")
    assert getattr(inst, "provider_name", "") == "deterministic"

    health = getattr(inst, "provider_health", {}) or {}
    assert health.get("ready") is False
    assert str(health.get("reason") or "") == "model_name_missing"


def test_colbert_factory_raises_when_hf_not_ready_and_strict_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag.reranker.factory import get_reranker

    monkeypatch.setattr(settings, "COLBERT_RERANK_PROVIDER", "hf", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_MODEL_NAME", "", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_HEALTHCHECK_STRICT", True, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_WARMUP_ENABLED", False, raising=False)

    with pytest.raises(ValueError, match="colbert_provider_unready"):
        _ = get_reranker("colbert")


def test_colbert_factory_warmup_failure_downgrades_to_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag.reranker.factory import get_reranker
    import app.rag.reranker.colbert as colbert_mod

    monkeypatch.setattr(settings, "COLBERT_RERANK_PROVIDER", "hf", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_MODEL_NAME", "colbert-ir/colbertv2.0", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_HEALTHCHECK_STRICT", False, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_WARMUP_ENABLED", True, raising=False)

    monkeypatch.setattr(
        colbert_mod,
        "check_colbert_provider_readiness",
        lambda **_kwargs: {"ready": True, "reason": "none", "provider": "hf"},
        raising=True,
    )
    monkeypatch.setattr(
        colbert_mod,
        "warmup_colbert_embedder",
        lambda **_kwargs: {"ok": False, "reason": "warmup_exception"},
        raising=True,
    )

    inst = get_reranker("colbert")
    assert getattr(inst, "provider_name", "") == "deterministic"
    health = getattr(inst, "provider_health", {}) or {}
    assert health.get("reason") == "warmup_exception"
