import asyncio
import copy
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest


def _kg_request():
    from app.rag.retrieval.planning.contracts import KGQueryRequest, KGQueryScope

    return KGQueryRequest("Ragvia", KGQueryScope(uuid4(), "actor", (), None, (uuid4(), uuid4())))


def _kg_settings():
    from app.rag.retrieval.planning.contracts import KGExpansionSettings

    return KGExpansionSettings(True, True, 3, 2, 0.15, ("Skill",))


def test_deterministic_expansion_preserves_bounded_alias_and_dictionary_results(monkeypatch):
    from app.query import expand
    from app.rag.retrieval.planning.contracts import AliasQuerySettings, DeterministicExpansionRequest
    from app.rag.retrieval.planning.planner import expand_deterministic_queries

    monkeypatch.setattr(
        expand, "load_base_dictionary_rules", lambda: {"Ragvia": ["knowledge platform", "another term"]}
    )
    result = expand_deterministic_queries(
        DeterministicExpansionRequest("Ragvia retrieval", AliasQuerySettings(True, {"Ragvia": ["RAG", "KB"]}, 1))
    )
    assert result.alias.queries == ["RAG retrieval"]
    assert result.alias.metadata["generated"] == 1
    assert [item["expanded_text"] for item in result.dictionary.expansions] == ["knowledge platform retrieval"]
    assert result.dictionary.failure is None


def test_dictionary_failure_keeps_alias_results_and_the_original_error(monkeypatch):
    from app.query import expand
    from app.rag.retrieval.planning.contracts import AliasQuerySettings, DeterministicExpansionRequest
    from app.rag.retrieval.planning.planner import expand_deterministic_queries

    failure = OSError("dictionary unavailable")

    def fail():
        raise failure

    monkeypatch.setattr(expand, "load_base_dictionary_rules", fail)
    result = expand_deterministic_queries(
        DeterministicExpansionRequest("Ragvia", AliasQuerySettings(True, {"Ragvia": ["RAG"]}, 1))
    )
    assert result.alias.queries == ["RAG"]
    assert result.dictionary.expansions == [] and result.dictionary.failure is failure
    assert result.dictionary.metadata["error"] == "dictionary unavailable"


def test_kg_expansion_preserves_scope_stable_selection_and_response_for_later_consumers(monkeypatch):
    from app.rag.kg import pipeline
    from app.rag.retrieval.planning.knowledge_graph import expand_kg_query

    request = _kg_request()
    payload = {
        "entities": [
            {"name": "Skill thing", "type": "Skill", "weight": "unused invalid weight"},
            {"name": "Zeta", "type": "Organization", "weight": 0.9},
            {"name": "API", "type": "Technology", "weight": 0.9},
            {"name": "api", "type": "Technology", "weight": 0.8},
            {"name": "Ragvia", "type": "Organization", "weight": 1.0},
            {"name": "Beta", "type": "Technology", "weight": 0.7},
        ],
        "events": [{"title": "later evidence"}],
    }
    original = copy.deepcopy(payload)
    received = []

    async def search(**kwargs):
        received.append(kwargs)
        return payload

    monkeypatch.setattr(pipeline, "kg_search", search)
    result = expand_kg_query(request, settings=_kg_settings())
    assert result.failure is None
    assert result.queries == ["Ragvia API", "Ragvia Zeta"]
    assert result.entity_names == ["API", "Zeta"]
    assert result.entities_total == 6 and result.entities_selected == 3
    assert result.response is payload and payload == original
    assert received == [
        {
            "query": "Ragvia",
            "tenant_id": request.scope.tenant_id,
            "account_id": "actor",
            "document_ids": [],
            "dataset_id": None,
            "dataset_ids": list(request.scope.dataset_ids),
        }
    ]


@pytest.mark.parametrize(
    "condition", ["disabled", "service_disabled", "tenant_missing", "scope_missing", "account_missing"]
)
def test_kg_expansion_does_not_search_without_its_actual_scope_and_capability(monkeypatch, condition):
    from app.rag.kg import pipeline
    from app.rag.retrieval.planning.knowledge_graph import expand_kg_query

    request, settings = _kg_request(), _kg_settings()
    if condition == "disabled":
        settings = replace(settings, enabled=False)
    elif condition == "service_disabled":
        settings = replace(settings, service_enabled=False)
    elif condition == "tenant_missing":
        request = replace(request, scope=replace(request.scope, tenant_id=None))
    elif condition == "scope_missing":
        request = replace(request, scope=replace(request.scope, dataset_ids=()))
    else:
        request = replace(request, scope=replace(request.scope, account_id=None))

    async def unused(**kwargs):
        pytest.fail("KG query escaped capability/scope admission")

    monkeypatch.setattr(pipeline, "kg_search", unused)
    result = expand_kg_query(request, settings=settings)
    assert result.queries == [] and result.response is None
    assert result.elapsed_sec == 0.0 and result.failure is None


def test_kg_search_failure_preserves_the_original_error(monkeypatch):
    from app.rag.kg import pipeline
    from app.rag.retrieval.planning.knowledge_graph import expand_kg_query

    failure = ConnectionError("KG unavailable")

    async def search(**kwargs):
        raise failure

    monkeypatch.setattr(pipeline, "kg_search", search)
    result = expand_kg_query(_kg_request(), settings=_kg_settings())
    assert result.failure is failure and result.queries == [] and result.response is None


@pytest.mark.parametrize(
    "payload,error_type",
    [
        ([], TypeError),
        ({"entities": "invalid array"}, TypeError),
        ({"entities": [{"name": "API", "type": "Technology", "weight": "invalid weight"}]}, ValueError),
    ],
)
def test_invalid_kg_response_is_a_visible_failure_instead_of_healthy_empty_results(monkeypatch, payload, error_type):
    from app.rag.kg import pipeline
    from app.rag.retrieval.planning.knowledge_graph import expand_kg_query

    async def search(**kwargs):
        return payload

    monkeypatch.setattr(pipeline, "kg_search", search)
    result = expand_kg_query(_kg_request(), settings=_kg_settings())
    assert isinstance(result.failure, error_type)
    assert result.queries == []


@pytest.mark.asyncio
async def test_kg_sync_operation_runs_in_its_owned_worker_when_a_loop_is_running(monkeypatch):
    from app.rag.kg import pipeline
    from app.rag.retrieval.planning.knowledge_graph import expand_kg_query

    parent_thread = threading.get_ident()
    workers = []

    async def search(**kwargs):
        workers.append(threading.get_ident())
        return {"entities": []}

    monkeypatch.setattr(pipeline, "kg_search", search)
    result = expand_kg_query(_kg_request(), settings=_kg_settings())
    assert result.failure is None and result.queries == []
    assert len(workers) == 1 and workers[0] != parent_thread


def test_kg_cancellation_is_not_converted_to_optional_success(monkeypatch):
    from app.rag.kg import pipeline
    from app.rag.retrieval.planning.knowledge_graph import expand_kg_query

    failure = asyncio.CancelledError("cancelled")

    async def search(**kwargs):
        raise failure

    monkeypatch.setattr(pipeline, "kg_search", search)
    with pytest.raises(asyncio.CancelledError) as caught:
        expand_kg_query(_kg_request(), settings=_kg_settings())
    assert caught.value is failure


@pytest.mark.parametrize("invalid_entities", [False, True])
def test_orchestrator_reuses_one_scoped_kg_read_for_expansion_and_evidence(monkeypatch, invalid_entities):
    from app.infrastructure.config import settings
    from app.rag.kg import pipeline
    from app.rag.retrieval.planning import planner as query_planning
    from app.rag.retrieval.stages import knowledge_graph, preparation
    from app.rag.retrieval.stages.state import RetrievalRuntimeState
    from tests.query_model_fixtures import ModelReplies

    for field in ("KG_ENABLED", "KG_CHAT_ENABLED"):
        monkeypatch.setattr(settings, field, True)
    tenant_id, dataset_a, dataset_b = uuid4(), uuid4(), uuid4()
    state = {
        "tenant_id": tenant_id,
        "account_id": "actor",
        "dataset_ids": [dataset_a, dataset_b],
        "enable_kg_query_expansion": True,
    }
    payload = {
        "entities": [{"name": "API", "type": "Technology", "weight": "invalid" if invalid_entities else 0.9}],
        "events": [],
    }
    calls = []

    async def search(**kwargs):
        calls.append(kwargs)
        return payload

    monkeypatch.setattr(pipeline, "kg_search", search)
    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False)
    state.update(
        {
            "enable_query_rewrite": False,
            "enable_multi_query": False,
            "enable_hyde": False,
            "enable_query_decomposition": False,
            "intent_router": False,
            "adaptive_router": False,
        }
    )
    request = preparation._build_retrieval_request(state, question="Ragvia", history_text="")
    plan = query_planning.prepare_query_plan(request, models=ModelReplies())
    ctx = RetrievalRuntimeState(state=state, question="Ragvia", history_text="")
    ctx.query_plan = plan
    preparation._run_retrieval_kg_query_expansion_phase(ctx)
    ctx.kg_chunk_injection_max_chunks = 5
    assert ctx.query_plan.kg.response is payload
    assert ctx.query_plan.kg.queries == ([] if invalid_entities else ["Ragvia API"])
    assert (ctx.query_plan.kg.failure is not None) is invalid_entities
    if invalid_entities:
        with pytest.raises(ValueError) as caught:
            knowledge_graph._run_kg_injection(ctx)
        assert caught.value is ctx.query_plan.kg.failure
    else:
        assert knowledge_graph._run_kg_injection(ctx) == []
    assert len(calls) == 1
    assert calls[0]["tenant_id"] == tenant_id and calls[0]["account_id"] == "actor"
    assert calls[0]["dataset_ids"] == [dataset_a, dataset_b]


def test_evidence_does_not_repeat_a_kg_response_already_rejected_as_invalid(monkeypatch):
    from langchain_core.documents import Document

    from app.infrastructure.config import settings
    from app.rag.kg import pipeline
    from app.rag.retrieval.planning import planner as query_planning
    from app.rag.retrieval.stages import knowledge_graph, preparation
    from app.rag.retrieval.stages.state import RetrievalRuntimeState
    from tests.query_model_fixtures import ModelReplies

    monkeypatch.setattr(settings, "KG_ENABLED", True)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True)
    state = {"tenant_id": uuid4(), "account_id": "actor", "dataset_id": uuid4(), "enable_kg_query_expansion": True}
    calls = []

    async def search(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(pipeline, "kg_search", search)
    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False)
    state.update(
        {
            "enable_query_rewrite": False,
            "enable_multi_query": False,
            "enable_hyde": False,
            "enable_query_decomposition": False,
            "intent_router": False,
            "adaptive_router": False,
        }
    )
    request = preparation._build_retrieval_request(state, question="Ragvia", history_text="")
    plan = query_planning.prepare_query_plan(request, models=ModelReplies())
    ctx = RetrievalRuntimeState(state=state, question="Ragvia", history_text="")
    ctx.query_plan = plan
    preparation._run_retrieval_kg_query_expansion_phase(ctx)
    ctx.kg_chunk_injection_max_chunks = 5
    failure = ctx.query_plan.kg.failure
    assert isinstance(failure, TypeError)
    with pytest.raises(TypeError) as caught:
        knowledge_graph._run_kg_injection(ctx)
    assert len(calls) == 1
    assert caught.value is failure
    assert ctx.kg_query_expansion_error == str(failure)
    main = [Document(page_content="main evidence")]
    ctx.docs = main
    ctx.state["enable_kg_chunk_injection"] = True
    recorded = []
    monkeypatch.setattr(
        knowledge_graph, "_log_orchestrator_fallback", lambda operation, error: recorded.append((operation, error))
    )
    knowledge_graph._run_retrieval_kg_injection_phase(ctx)
    assert ctx.docs is main and ctx.kg_chunks_injected == 0
    assert ctx.kg_chunk_injection_error == str(failure)
    assert recorded == [("kg_chunk_injection", failure)]
    assert len(calls) == 1


def test_kg_injection_reads_once_when_query_expansion_did_not_run(monkeypatch):
    from app.infrastructure.config import settings
    from app.rag.kg import pipeline
    from app.rag.retrieval.planning import planner
    from app.rag.retrieval.stages import knowledge_graph, preparation
    from app.rag.retrieval.stages.state import RetrievalRuntimeState
    from tests.query_model_fixtures import ModelReplies

    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False)
    state = {
        "tenant_id": uuid4(),
        "account_id": "actor",
        "dataset_id": uuid4(),
        "enable_kg_query_expansion": False,
        "enable_query_rewrite": False,
        "enable_multi_query": False,
        "enable_hyde": False,
        "enable_query_decomposition": False,
        "industry_rules_enabled": False,
        "intent_router": False,
        "adaptive_router": False,
    }
    request = preparation._build_retrieval_request(state, question="Ragvia", history_text="")
    ctx = RetrievalRuntimeState(state=state, question="Ragvia", history_text="")
    ctx.query_plan = planner.prepare_query_plan(request, models=ModelReplies())
    preparation._run_retrieval_kg_query_expansion_phase(ctx)
    ctx.kg_chunk_injection_max_chunks = 5
    calls = []

    async def search(**scope):
        calls.append(scope)
        return {"events": []}

    monkeypatch.setattr(pipeline, "kg_search", search)
    assert ctx.query_plan.kg.failure is None and ctx.kg_result_cached is None
    assert knowledge_graph._run_kg_injection(ctx) == []
    assert len(calls) == 1
    assert calls[0]["tenant_id"] == state["tenant_id"] and calls[0]["account_id"] == "actor"


def test_expansions_execute_without_importing_the_upper_rag_adapters() -> None:
    script = """
import importlib.abc
import sys
from uuid import uuid4
class NoAdapters(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'app.rag.runtime.engine','app.rag.retrieval.recall.retriever','app.rag.retrieval.orchestrator'}:
            raise AssertionError('Expansion imports upper adapter: ' + fullname)
sys.meta_path.insert(0, NoAdapters())
from app.query import expand
from app.rag.kg import pipeline
from app.rag.retrieval.planning.contracts import AliasQuerySettings, DeterministicExpansionRequest, KGQueryRequest, KGQueryScope, KGExpansionSettings
from app.rag.retrieval.planning.planner import expand_deterministic_queries
from app.rag.retrieval.planning.knowledge_graph import expand_kg_query
expand.load_base_dictionary_rules = lambda: {'Ragvia': ['knowledge platform']}
deterministic = expand_deterministic_queries(DeterministicExpansionRequest('Ragvia',AliasQuerySettings(True,{'Ragvia':['RAG']},1)))
assert deterministic.alias.queries == ['RAG']
assert deterministic.dictionary.expansions[0]['expanded_text'] == 'knowledge platform'
async def search(**kwargs):
    return {'entities':[{'name':'API','type':'Technology','weight':0.9}]}
pipeline.kg_search = search
request = KGQueryRequest('Ragvia',KGQueryScope(uuid4(),'actor',(),uuid4()))
result = expand_kg_query(request,settings=KGExpansionSettings(True,True,3,2,0.15,()))
assert result.failure is None and result.queries == ['Ragvia API']
assert 'app.rag.retrieval.orchestrator' not in sys.modules
assert 'app.rag.runtime.engine' not in sys.modules
assert 'app.rag.retrieval.recall.retriever' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
