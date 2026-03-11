from __future__ import annotations

import pytest

from app.core.config import settings


def _build_key(*, provider: str) -> str:
    import app.rag.rerank_result_cache as cache_mod

    return cache_mod.build_evidence_post_rerank_cache_key(
        tenant_id="t",
        account_id="u",
        provider=provider,
        top_n=10,
        query="keying-query",
        candidates_fingerprint="cand-fp",
        corpus_cache_token="corp-v1",
    )


def test_rerank_cache_key_changes_with_colbert_provider_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "COLBERT_RERANK_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_MODEL_NAME", "model-a", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_DEVICE", "cpu", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_BATCH_SIZE", 16, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_MAX_LENGTH", 256, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_EMBED_DIM", 64, raising=False)
    key_a = _build_key(provider="colbert")

    monkeypatch.setattr(settings, "COLBERT_RERANK_PROVIDER", "hf", raising=False)
    key_b = _build_key(provider="colbert")

    monkeypatch.setattr(settings, "COLBERT_RERANK_MODEL_NAME", "model-b", raising=False)
    key_c = _build_key(provider="colbert")

    assert key_a != key_b
    assert key_b != key_c


def test_rerank_cache_key_changes_with_ltr_manifest_and_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LTR_MODEL_PATH", "/tmp/ltr-model-v1.bin", raising=False)
    monkeypatch.setattr(settings, "LTR_MODEL_MANIFEST_PATH", "/tmp/ltr-manifest-a.json", raising=False)
    monkeypatch.setattr(settings, "LTR_FEATURE_SPEC_VERSION", 2, raising=False)
    key_a = _build_key(provider="ltr")

    monkeypatch.setattr(settings, "LTR_MODEL_MANIFEST_PATH", "/tmp/ltr-manifest-b.json", raising=False)
    key_b = _build_key(provider="ltr")

    monkeypatch.setattr(settings, "LTR_FEATURE_SPEC_VERSION", 3, raising=False)
    key_c = _build_key(provider="ltr")

    assert key_a != key_b
    assert key_b != key_c


def test_rerank_cache_key_normalizes_provider_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "COLBERT_RERANK_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_MODEL_NAME", "model-a", raising=False)

    key_a = _build_key(provider="colbert")
    key_b = _build_key(provider="late_interaction")
    assert key_a == key_b
