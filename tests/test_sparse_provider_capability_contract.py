from __future__ import annotations

from app.rag.retrieval.sparse import (
    VALID_SPARSE_PROVIDERS,
    resolve_sparse_provider_capability,
)


def test_sparse_capability_ready_for_deterministic_provider() -> None:
    status = resolve_sparse_provider_capability(
        requested_provider="deterministic",
        sparse_enabled=True,
        splade_model_name="",
    )

    assert status["status"] == "ready"
    assert status["reason"] == "none"
    assert status["effective_provider"] == "deterministic"
    assert status["provider_supported"] is True
    assert set(VALID_SPARSE_PROVIDERS) == {"deterministic", "splade"}


def test_sparse_capability_falls_back_on_invalid_provider() -> None:
    status = resolve_sparse_provider_capability(
        requested_provider="totally-unknown-provider",
        sparse_enabled=True,
        splade_model_name="",
    )

    assert status["status"] == "fallback"
    assert status["reason"] == "provider_invalid"
    assert status["requested_provider"] == "totally-unknown-provider"
    assert status["effective_provider"] == "deterministic"
    assert status["provider_supported"] is False


def test_sparse_capability_falls_back_when_splade_model_missing() -> None:
    status = resolve_sparse_provider_capability(
        requested_provider="splade",
        sparse_enabled=True,
        splade_model_name="",
    )

    assert status["status"] == "fallback"
    assert status["reason"] == "splade_model_missing"
    assert status["effective_provider"] == "splade"
    assert status["model_required"] is True
    assert status["model_configured"] is False


def test_sparse_capability_disabled_state() -> None:
    status = resolve_sparse_provider_capability(
        requested_provider="splade",
        sparse_enabled=False,
        splade_model_name="intfloat/splade-v3",
    )

    assert status["status"] == "disabled"
    assert status["reason"] == "sparse_disabled"
    assert status["effective_provider"] == "splade"
