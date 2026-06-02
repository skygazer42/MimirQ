from __future__ import annotations

import pytest


def test_openai_reranker_payload_omits_provider_specific_max_chunks_by_default() -> None:
    from app.rag.reranker.openai import OpenAIReranker

    reranker = OpenAIReranker(
        model_name="bge-reranker-large",
        api_key="test-key",
        base_url="http://example.test/v1/rerank",
    )

    payload = reranker._build_payload("q", ["a", "b"], max_length=512)  # noqa: SLF001

    assert payload == {
        "model": "bge-reranker-large",
        "query": "q",
        "documents": ["a", "b"],
    }


def test_openai_reranker_payload_can_opt_into_max_chunks() -> None:
    from app.rag.reranker.openai import OpenAIReranker

    reranker = OpenAIReranker(
        model_name="bge-reranker-large",
        api_key="test-key",
        base_url="http://example.test/v1/rerank",
        parameters={"include_max_chunks_per_doc": True},
    )

    payload = reranker._build_payload("q", ["a"], max_length=256)  # noqa: SLF001

    assert payload["max_chunks_per_doc"] == 256


def test_openai_reranker_ignores_unsupported_socks_proxy_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.reranker.base as base_mod
    from app.rag.reranker.openai import OpenAIReranker

    captured: list[dict[str, object]] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"results": [{"index": 0, "relevance_score": 2.0}]}

    class _Client:
        def __init__(self, **kwargs: object) -> None:
            captured.append(dict(kwargs))

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, *_args: object, **_kwargs: object) -> _Response:
            return _Response()

    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:35983/")
    monkeypatch.setattr(base_mod.httpx, "Client", _Client, raising=True)

    reranker = OpenAIReranker(
        model_name="bge-reranker-large",
        api_key="test-key",
        base_url="http://example.test/v1/rerank",
    )

    scores = reranker.compute_score("q", ["doc"], normalize=False)

    assert scores == [2.0]
    assert captured
    assert captured[0]["trust_env"] is False


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
    import app.rag.reranker.colbert as colbert_mod
    from app.core.config import settings
    from app.rag.reranker.factory import get_reranker

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
