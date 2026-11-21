from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.prompts import ChatPromptTemplate


def _engine():
    return SimpleNamespace(
        models={"default": FakeListChatModel(responses=["default"])},
        multi_query_prompt=ChatPromptTemplate.from_template("{query} count {n}"),
        hyde_prompt=ChatPromptTemplate.from_template("{query}"),
        step_back_prompt=ChatPromptTemplate.from_template("{query}"),
        decompose_prompt=ChatPromptTemplate.from_template("{query} count {n}"),
    )


@pytest.mark.asyncio
async def test_model_bindings_preserve_fast_selected_and_default_precedence() -> None:
    from app.rag.runtime.query_models import EngineQueryModels

    engine = _engine()
    selected = FakeListChatModel(responses=["selected"])
    calls = EngineQueryModels(lambda: engine, fallback_model=selected)
    assert await calls.hyde(temperature=0.0).ainvoke(query="q") == "selected"
    engine.models["fast"] = FakeListChatModel(responses=["fast"])
    assert await calls.decompose(max_questions=2, temperature=0.0).ainvoke(query="q") == "fast"
    engine.models.pop("fast")
    default = EngineQueryModels(lambda: engine)
    assert default.multi_query(count=2, temperature=0.0).invoke(query="q") == "default"


def test_model_bindings_resolve_lazily_and_keep_required_model_errors_explicit() -> None:
    from app.rag.runtime.query_models import EngineQueryModels

    resolved = []
    engine = _engine()
    calls = EngineQueryModels(lambda: resolved.append("resolved") or engine)
    assert resolved == []
    engine.models.clear()
    with pytest.raises(KeyError, match="default"):
        calls.step_back(temperature=0.0)
    assert resolved == ["resolved"]


def test_shared_query_settings_keep_experiment_caps_and_disabled_alias_semantics(monkeypatch) -> None:
    from app.infrastructure.config import settings
    from app.rag.retrieval.planning.contracts import ModelQueryOverrides
    from app.rag.retrieval.planning.options import resolve_alias_query_settings, resolve_model_query_settings

    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False)
    monkeypatch.setattr(settings, "MULTI_QUERY_COUNT_CAP", 3)
    result = resolve_model_query_settings(
        ModelQueryOverrides(multi_query_count=99, multi_query_temperature=9.0, multi_query_ab_variant="ON")
    )
    assert result.multi_query.enabled and result.multi_query.experiment.forced
    assert result.multi_query.count == 3 and result.multi_query.temperature == 2.0
    aliases = resolve_alias_query_settings(enabled=None, aliases={"SSO": ["single sign-on"]}, max_queries=0)
    assert aliases.enabled is True and aliases.max_queries == 0
    disabled = resolve_alias_query_settings(enabled=False, aliases={"SSO": ["single sign-on"]}, max_queries=None)
    assert disabled.enabled is False and disabled.max_queries == 5
