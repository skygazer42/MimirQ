import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_get_reranker_rejects_unknown_provider() -> None:
    from app.rag.reranker.factory import get_reranker

    with pytest.raises(ValueError, match="Unknown reranker provider: 'typo-provider'"):
        get_reranker("typo-provider")


def test_get_reranker_disabled_alias_still_uses_existing_unknown_error_contract() -> None:
    from app.rag.reranker.factory import get_reranker

    with pytest.raises(ValueError, match="Unknown reranker provider: 'none'"):
        get_reranker("none")


def test_pc_reranker_is_local_parent_child_implementation() -> None:
    from app.rag.reranker.factory import get_reranker
    from app.rag.reranker.parent_child import ParentChildReranker
    from app.rag.reranker.types import RerankCandidate

    reranker = get_reranker("pc")
    result = reranker.rerank(
        "query",
        [
            RerankCandidate(id="low", text="low", metadata={"score": 0.1}),
            RerankCandidate(id="high", text="high", metadata={"score": 0.9}),
        ],
        top_n=2,
    )

    assert isinstance(reranker, ParentChildReranker)
    assert result.ordered_ids == ["high", "low"]


@pytest.mark.parametrize(
    ("provider", "kwargs", "expected"),
    [
        ("cross-encoder", {}, {"provider": "cross_encoder", "tier": "prod"}),
        ("sentence-transformers", {}, {"provider": "cross_encoder", "tier": "prod"}),
        ("pc", {}, {"provider": "pc", "tier": "prod"}),
        ("aliyun", {}, {"provider": "aliyun", "tier": "experimental"}),
        ("off", {}, {"provider": "none", "tier": "disabled"}),
    ],
)
def test_describe_reranker_provider_preserves_existing_alias_contracts(
    provider: str,
    kwargs: dict[str, object],
    expected: dict[str, object],
) -> None:
    from app.rag.reranker.factory import describe_reranker_provider

    assert describe_reranker_provider(provider, **kwargs) == expected


def test_describe_reranker_provider_keeps_colbert_default_mode_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.reranker.factory import describe_reranker_provider

    monkeypatch.setattr(
        "app.rag.reranker.capabilities.settings.COLBERT_RERANK_PROVIDER", "deterministic", raising=False
    )
    assert describe_reranker_provider("late_interaction") == {
        "provider": "colbert",
        "tier": "offline_only",
        "mode": "deterministic",
    }


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


def test_get_reranker_imports_only_requested_provider_on_demand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.reranker import factory

    calls: list[tuple[str, str]] = []

    class FakeOpenAIReranker:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    def _load_attr(module_name: str, attr_name: str) -> object:
        calls.append((module_name, attr_name))
        if (module_name, attr_name) == ("app.rag.reranker.openai", "OpenAIReranker"):
            return FakeOpenAIReranker
        raise AssertionError(f"unexpected import target: {(module_name, attr_name)!r}")

    monkeypatch.setattr(factory, "_load_attr", _load_attr, raising=True)
    factory._api_reranker_cache.clear()

    reranker = factory.get_reranker(
        "openai",
        model_name="test-model",
        api_key="test-key",
        base_url="https://reranker.example/v1/rerank",
    )

    assert isinstance(reranker, FakeOpenAIReranker)
    assert calls == [("app.rag.reranker.openai", "OpenAIReranker")]


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


def test_reranker_capability_discovery_reports_aliases_without_importing_providers() -> None:
    from app.rag.reranker.capabilities import get_reranker_capabilities, list_reranker_capabilities

    capability = get_reranker_capabilities("aliyun")
    families = {item["resolved_provider"]: item for item in list_reranker_capabilities()}

    assert capability["requested_provider"] == "aliyun"
    assert capability["resolved_provider"] == "dashscope"
    assert capability["aliases"] == ["dashscope", "aliyun"]
    assert capability["category"] == "api"
    assert "app.rag.reranker.dashscope" in capability["lazy_modules"]
    assert families["parent_child"]["aliases"] == ["parent_child", "pc"]


def test_reranker_factory_module_import_is_lazy_in_fresh_interpreter() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    script = """
import importlib
import json
import sys

provider_modules = [
    "app.rag.reranker.openai",
    "app.rag.reranker.dashscope",
    "app.rag.reranker.cross_encoder",
    "app.rag.reranker.colbert",
    "app.rag.reranker.ltr",
    "app.rag.reranker.long_context_rerank",
    "app.rag.reranker.local_bge_v2_m3",
    "app.rag.reranker.parent_child",
    "app.rag.reranker.hybrid",
    "app.rag.reranker.kg",
    "app.rag.reranker.llm_based",
    "app.rag.reranker.mmr",
]
for name in provider_modules:
    sys.modules.pop(name, None)
importlib.import_module("app.rag.reranker.factory")
from app.rag.reranker.capabilities import list_reranker_capabilities
list_reranker_capabilities()
print(json.dumps([name for name in provider_modules if name in sys.modules]))
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(proc.stdout.strip()) == []


def test_get_rag_reranker_preserves_legacy_default_and_pc_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.reranker import factory

    calls: list[str] = []

    monkeypatch.setattr(factory, "get_reranker", lambda provider: calls.append(provider) or provider, raising=True)

    assert factory.get_rag_reranker() == "llm"
    assert factory.get_rag_reranker("pc") == "parent_child"
    assert calls == ["llm", "parent_child"]
