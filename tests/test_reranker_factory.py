import importlib

import pytest


def test_get_reranker_rejects_unknown_provider() -> None:
    from app.rag.reranker.factory import get_reranker

    with pytest.raises(ValueError, match="Unknown reranker provider: 'typo-provider'"):
        get_reranker("typo-provider")


def test_get_reranker_passes_explicit_openai_timeout_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.reranker import factory, openai

    captured: dict[str, object] = {}

    class FakeOpenAIReranker:
        def __init__(
            self,
            *,
            model_name: str,
            api_key: str,
            base_url: str,
            timeout: float,
            **kwargs: object,
        ) -> None:
            captured.update(
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                kwargs=kwargs,
            )

    monkeypatch.setattr(openai, "OpenAIReranker", FakeOpenAIReranker)
    factory._api_reranker_cache.clear()

    reranker = factory.get_reranker(
        "openai",
        model_name="test-model",
        api_key="test-key",
        base_url="https://reranker.example/v1/rerank",
        timeout=7.5,
        parameters={"include_max_chunks_per_doc": True},
    )

    assert isinstance(reranker, FakeOpenAIReranker)
    assert captured["timeout"] == 7.5
    assert captured["kwargs"] == {"parameters": {"include_max_chunks_per_doc": True}}


@pytest.mark.parametrize(
    ("provider", "module_name", "class_name"),
    [
        ("openai", "app.rag.reranker.openai", "OpenAIReranker"),
        ("dashscope", "app.rag.reranker.dashscope", "DashScopeReranker"),
    ],
)
def test_api_reranker_cache_keys_include_all_initialization_parameters_without_plaintext(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    module_name: str,
    class_name: str,
) -> None:
    from app.rag.reranker import factory

    class FakeReranker:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, class_name, FakeReranker)
    factory._api_reranker_cache.clear()

    common = {
        "model_name": "private-model",
        "api_key": "private-api-key",
        "base_url": "https://private.example/rerank",
    }
    first = factory.get_reranker(
        provider,
        **common,
        timeout=7.5,
        parameters={"instruct": "private-instruction", "options": {"alpha": 1, "beta": 2}},
    )
    same = factory.get_reranker(
        provider,
        **common,
        timeout=7.5,
        parameters={"options": {"beta": 2, "alpha": 1}, "instruct": "private-instruction"},
    )
    different_timeout = factory.get_reranker(
        provider,
        **common,
        timeout=8.0,
        parameters={"instruct": "private-instruction", "options": {"alpha": 1, "beta": 2}},
    )
    different_parameters = factory.get_reranker(
        provider,
        **common,
        timeout=7.5,
        parameters={"instruct": "different-instruction", "options": {"alpha": 1, "beta": 2}},
    )

    assert same is first
    assert different_timeout is not first
    assert different_parameters is not first
    assert len(factory._api_reranker_cache) == 3
    for cache_key in factory._api_reranker_cache:
        assert cache_key.startswith(f"{provider}:")
        assert len(cache_key.removeprefix(f"{provider}:")) == 64
        for private_value in (
            "private-model",
            "private-api-key",
            "private.example",
            "private-instruction",
            "different-instruction",
        ):
            assert private_value not in cache_key
