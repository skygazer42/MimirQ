import asyncio
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import count
from pathlib import Path

import pytest

from tests.query_model_fixtures import ModelReplies as _Models
from tests.query_model_fixtures import model_query_request as _request
from tests.query_model_fixtures import model_query_settings as _settings


def test_model_expansion_owns_generation_order_and_each_strategy_result() -> None:
    from app.rag.retrieval.planning.model_expansion import expand_model_queries

    models = _Models()
    result = expand_model_queries(_request(), models=models)
    assert sorted(call[1] for call in models.calls if call[0] == "invoke") == sorted(
        [
            "multi_query",
            "hyde",
            "step_back",
            "decomposition",
        ]
    )
    assert result.multi_query.queries == ["first", "second"]
    assert result.hyde.text == "hypothetical" and result.hyde.model_used == "hyde"
    assert result.step_back.text == "broader view" and result.step_back.parse_metadata["ok"] is True
    assert result.decomposition.queries == ["part one", "part two"]
    assert result.elapsed_sec >= 0.0


def test_independent_model_expansions_overlap_and_copy_request_context():
    from contextvars import ContextVar

    from app.rag.retrieval.planning.model_expansion import expand_model_queries

    trace = ContextVar("query_expansion_trace", default="missing")
    trace.set("request-1")
    barrier = threading.Barrier(4)

    class ConcurrentModels(_Models):
        def _select(self, kind):
            response = self.replies[kind]

            class Model:
                model_name = kind

                def invoke(self, *, query):
                    assert trace.get() == "request-1"
                    barrier.wait(timeout=2)
                    return response

            return Model()

    result = expand_model_queries(_request(), models=ConcurrentModels())
    assert result.multi_query.queries == ["first", "second"]
    assert result.decomposition.queries == ["part one", "part two"]
    assert result.hyde.text == "hypothetical" and result.step_back.text == "broader view"


@pytest.mark.asyncio
async def test_native_async_model_expansions_overlap_without_background_tasks():
    from app.rag.retrieval.planning.model_expansion import expand_model_queries_async
    from tests.query_model_fixtures import AsyncReplies

    started = set()
    all_started = asyncio.Event()

    class ConcurrentModels(AsyncReplies):
        def _select(self, kind):
            response = self.replies[kind]

            class Model:
                model_name = kind

                async def ainvoke(self, *, query):
                    started.add(kind)
                    if len(started) == 4:
                        all_started.set()
                    await asyncio.wait_for(all_started.wait(), 1)
                    return response

            return Model()

    result = await expand_model_queries_async(_request(), models=ConcurrentModels())
    assert len(started) == 4
    assert result.multi_query.queries == ["first", "second"] and result.decomposition.queries == [
        "part one",
        "part two",
    ]


def test_disabled_and_zero_budget_strategies_do_not_resolve_models() -> None:
    from app.rag.retrieval.planning.model_expansion import expand_model_queries

    settings = _settings()
    settings = replace(
        settings,
        multi_query=replace(settings.multi_query, count=0),
        hyde=replace(settings.hyde, max_chars=0),
        step_back=replace(settings.step_back, enabled=False),
        decomposition=replace(settings.decomposition, max_questions=0),
    )
    models = _Models()
    result = expand_model_queries(_request(settings=settings), models=models)
    assert models.calls == []
    assert not (result.multi_query.used or result.hyde.used or result.step_back.used or result.decomposition.used)


def test_keyword_mode_skips_hyde_and_text_outputs_keep_their_existing_bounds() -> None:
    from app.rag.retrieval.planning.model_expansion import expand_model_queries

    settings = _settings()
    settings = replace(
        settings,
        hyde=replace(settings.hyde, output_max_chars=5),
        step_back=replace(settings.step_back, output_max_chars=5),
    )
    result = expand_model_queries(
        _request(settings=settings), models=_Models(hyde="  abcdefgh  ", step_back='"broader query"')
    )
    assert result.hyde.text == "abcde..." and result.step_back.text == "broad..."
    models = _Models()
    keyword = expand_model_queries(_request(mode="keyword"), models=models)
    assert keyword.hyde.used is False and ("resolve", "hyde") not in models.calls


def test_seeded_multi_query_order_is_independent_of_model_array_order() -> None:
    from app.rag.retrieval.planning.model_expansion import generate_multi_queries

    settings = _settings().multi_query
    settings = replace(settings, experiment=replace(settings.experiment, seed="experiment"))
    first = generate_multi_queries(
        "base", settings=settings, models=_Models(multi_query='["zeta", "alpha", "beta", "base"]')
    )
    second = generate_multi_queries(
        "base", settings=settings, models=_Models(multi_query='["beta", "zeta", "alpha", "base"]')
    )
    assert first.queries == second.queries and set(first.queries) == {"alpha", "beta", "zeta"}


@pytest.mark.parametrize("kind", ["multi_query", "hyde", "step_back", "decomposition"])
def test_optional_model_failure_retains_the_original_exception(kind, monkeypatch) -> None:
    from app.rag.retrieval.planning import model_expansion

    clock = count(step=0.25)
    monkeypatch.setattr(model_expansion.time, "perf_counter", lambda: next(clock))
    failure = TimeoutError(kind + " unavailable")
    result = model_expansion.expand_model_queries(_request(), models=_Models(**{kind: failure}))
    outcome = getattr(result, kind)
    assert outcome.failure is failure and outcome.used is False
    assert outcome.elapsed_sec == 0.25


@pytest.mark.parametrize("raw", ['[1, "valid text"]', "[null]", '[{"query":"wrong shape"}]'])
def test_invalid_model_array_is_a_visible_contract_failure(raw) -> None:
    from app.rag.retrieval.planning.model_expansion import generate_multi_queries

    result = generate_multi_queries("base", settings=_settings().multi_query, models=_Models(multi_query=raw))
    assert result.queries == [] and isinstance(result.failure, ValueError)
    assert result.parse_metadata["ok"] is False


def test_step_back_duplicate_is_an_unused_variant_with_an_explicit_reason() -> None:
    from app.rag.retrieval.planning.model_expansion import generate_step_back_query

    result = generate_step_back_query("base", settings=_settings().step_back, models=_Models(step_back='"base"'))
    assert result.text == "" and result.used is False and result.failure is None
    assert result.parse_metadata == {"ok": False, "method": "text", "error": "empty_or_duplicate"}


def test_decomposition_deduplicates_after_truncation() -> None:
    from app.rag.retrieval.planning.model_expansion import decompose_query

    prefix = "x" * 510
    raw = '["' + prefix + 'a", "' + prefix + 'b"]'
    result = decompose_query("base", settings=_settings().decomposition, models=_Models(decomposition=raw))
    assert result.queries == ["x" * 500 + "..."]
    assert result.parse_metadata["ok"] is True


def test_heuristic_decomposition_keeps_canonical_queries_unique_after_truncation() -> None:
    from app.rag.retrieval.planning.model_expansion import decompose_query

    settings = replace(_settings().decomposition, heuristic_enabled=True, model_api_key_present=False, max_chars=0)
    prefix = "x" * 510
    result = decompose_query(prefix + "a? " + prefix + "b?", settings=settings, models=_Models())
    assert result.queries == ["x" * 500 + "..."]


def test_decomposition_uses_the_defined_heuristic_when_no_model_is_configured() -> None:
    from app.rag.retrieval.planning.model_expansion import decompose_query

    settings = replace(_settings().decomposition, heuristic_enabled=True, model_api_key_present=False)
    models = _Models()
    result = decompose_query("合同的有效期限是多少？付款的具体条件是什么？", settings=settings, models=models)
    assert result.queries == ["合同的有效期限是多少", "付款的具体条件是什么"]
    assert result.parse_metadata["method"] == "heuristic" and result.failure is None
    assert models.calls == []


def test_decomposition_heuristic_fallback_retains_the_failed_model_outcome() -> None:
    from app.rag.retrieval.planning.model_expansion import decompose_query

    failure = TimeoutError("decomposition timed out")
    settings = replace(_settings().decomposition, heuristic_enabled=True)
    result = decompose_query(
        "合同的有效期限是多少？付款的具体条件是什么？", settings=settings, models=_Models(decomposition=failure)
    )
    assert result.queries == ["合同的有效期限是多少", "付款的具体条件是什么"]
    assert result.parse_metadata["method"] == "heuristic" and result.failure is failure
    assert result.model_used is None


def test_valid_empty_decomposition_does_not_trigger_heuristic_replacement() -> None:
    from app.rag.retrieval.planning.model_expansion import decompose_query

    settings = replace(_settings().decomposition, heuristic_enabled=True)
    result = decompose_query("合同期限是多少？付款条件是什么？", settings=settings, models=_Models(decomposition="[]"))
    assert result.queries == [] and result.failure is None
    assert result.parse_metadata["ok"] is True and result.parse_metadata["method"] != "heuristic"


def test_required_model_resolution_failure_and_cancellation_propagate() -> None:
    from app.rag.retrieval.planning.model_expansion import expand_model_queries

    failure = ValueError("required model missing")

    class MissingModel(_Models):
        def multi_query(self, **kwargs):
            raise failure

    with pytest.raises(ValueError) as caught:
        expand_model_queries(_request(), models=MissingModel())
    assert caught.value is failure
    cancelled = asyncio.CancelledError("cancelled")
    with pytest.raises(asyncio.CancelledError) as caught:
        expand_model_queries(_request(), models=_Models(multi_query=cancelled))
    assert caught.value is cancelled


def test_state_adapter_resolves_ab_override_and_bounded_multi_query_settings(monkeypatch) -> None:
    from app.infrastructure.config import settings
    from app.rag.retrieval.planning.options import parse_model_query_overrides, resolve_model_query_settings

    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False)
    monkeypatch.setattr(settings, "MULTI_QUERY_COUNT_CAP", 3)
    resolved = resolve_model_query_settings(
        parse_model_query_overrides(
            {"multi_query_ab_variant": "ON", "multi_query_count": 99, "multi_query_temperature": 9.0}
        )
    )
    assert resolved.multi_query.enabled is True and resolved.multi_query.experiment.forced is True
    assert resolved.multi_query.count == 3 and resolved.multi_query.temperature == 2.0
    disabled = resolve_model_query_settings(
        parse_model_query_overrides({"enable_multi_query": False, "multi_query_ab_variant": "on"})
    )
    assert disabled.multi_query.enabled is False and disabled.multi_query.experiment.forced is False


def test_parallel_model_operations_return_separate_queries_and_parse_metadata() -> None:
    from app.rag.retrieval.planning.model_expansion import expand_model_queries

    barrier = threading.Barrier(2)

    class SharedModels(_Models):
        def _select(self, kind):
            class Model:
                model_name = kind

                def invoke(self, *, query):
                    if kind == "multi_query":
                        barrier.wait(timeout=3)
                    if kind in {"multi_query", "decomposition"}:
                        return json.dumps([query + " expanded"])
                    return query + " context"

            return Model()

    models = SharedModels()
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(
            executor.map(lambda query: expand_model_queries(_request(query=query), models=models), ("first", "second"))
        )
    assert first.multi_query.queries == ["first expanded"]
    assert second.multi_query.queries == ["second expanded"]
    assert first.decomposition.queries == ["first expanded"]
    assert second.decomposition.queries == ["second expanded"]
    second.multi_query.parse_metadata["error"] = "caller mutation"
    assert first.multi_query.parse_metadata["error"] is None


def test_orchestrator_uses_real_model_ports_and_preserves_query_invocation_order(monkeypatch) -> None:
    from uuid import NAMESPACE_URL, uuid4, uuid5

    from langchain_core.documents import Document
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langchain_core.prompts import ChatPromptTemplate

    from app.infrastructure.config import settings
    from app.query import expand
    from app.rag.retrieval import orchestrator

    for field, value in {
        "ENABLE_QUERY_REWRITE": False,
        "ENABLE_MULTI_QUERY": True,
        "ENABLE_HYDE": True,
        "ENABLE_STEP_BACK_QUERY": True,
        "ENABLE_QUERY_DECOMPOSITION": True,
        "QUERY_DECOMPOSITION_MIN_CHARS": 0,
        "QUERY_DECOMPOSITION_HEURISTIC_FALLBACK_ENABLED": False,
        "RAG_DECOMPOSITION_CHAIN_ENABLED": False,
        "KG_ENABLED": False,
        "KG_CHAT_ENABLED": False,
        "RAG_KG_QUERY_EXPANSION_ENABLED": False,
        "RAG_KG_CHUNK_INJECTION_ENABLED": False,
        "EVIDENCE_POST_RERANK_ENABLED": False,
        "RAG_ABSTAIN_ENABLED": False,
        "RETRIEVAL_QUERY_PARALLELISM": 1,
    }.items():
        monkeypatch.setattr(settings, field, value)
    monkeypatch.setattr(expand, "load_base_dictionary_rules", lambda: {})

    class PromptReplies(FakeListChatModel):
        def _call(self, messages, **_options):
            prompt = messages[0].content
            return next(
                reply
                for prefix, reply in (
                    ("Variants", '["alternate"]'),
                    ("Hypothesis", "hypothetical"),
                    ("Broader", "broader"),
                    ("Questions", '["part query"]'),
                )
                if prompt.startswith(prefix)
            )

    class Engine:
        models = {"fast": PromptReplies(responses=["unused"])}
        multi_query_prompt = ChatPromptTemplate.from_template("Variants for {query}, count {n}")
        hyde_prompt = ChatPromptTemplate.from_template("Hypothesis for {query}")
        step_back_prompt = ChatPromptTemplate.from_template("Broader query for {query}")
        decompose_prompt = ChatPromptTemplate.from_template("Questions for {query}, count {n}")

    received = []
    document_id = uuid4()

    class Retriever:
        _last_debug_metrics = {}

        def model_copy(self, **kwargs):
            return self

        def invoke(self, query):
            received.append(query)
            chunk_id = str(uuid5(NAMESPACE_URL, query))
            return [
                Document(
                    page_content=query,
                    id=chunk_id,
                    metadata={
                        "document_id": str(document_id),
                        "chunk_id": chunk_id,
                        "source": "fixture.md",
                        "score": 0.8,
                    },
                )
            ]

    from app.infrastructure import tokens
    from app.rag.retrieval.stages import preparation
    from app.rag.runtime import engine as engine_runtime

    monkeypatch.setattr(tokens, "_get_encoder", lambda: False)
    monkeypatch.setattr(engine_runtime, "get_rag_engine", lambda: Engine())
    monkeypatch.setattr(preparation, "hybrid_retriever", Retriever())
    result = orchestrator.run_retrieval(
        {
            "question": "base query",
            "history": [],
            "tenant_id": uuid4(),
            "account_id": "actor",
            "document_ids": [document_id],
            "retrieval_mode": "hybrid",
            "top_k": 5,
            "enable_reranker": False,
            "industry_rules_enabled": False,
            "metrics": {},
        }
    )
    assert received == ["base query", "alternate", "broader", "part query", "hypothetical"]
    assert [item["kind"] for item in result["metrics"]["retrieval_per_query"]] == [
        "main",
        "mq",
        "step_back",
        "subq",
        "hyde",
    ]
    assert result["metrics"]["multi_query_used"] is True
    assert result["metrics"]["hyde_used"] is True
    assert result["metrics"]["decompose_used"] is True


def test_model_strategies_execute_without_importing_upper_adapters() -> None:
    script = """
import importlib.abc
import sys
class NoAdapters(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'app.rag.runtime.engine','app.rag.retrieval.recall.retriever','app.rag.retrieval.orchestrator'}:
            raise AssertionError('Model queries import upper adapter: ' + fullname)
sys.meta_path.insert(0, NoAdapters())
from app.rag.retrieval.planning.contracts import MultiQueryExperiment, MultiQuerySettings, TextQuerySettings, DecompositionSettings, ModelQuerySettings, ModelQueryRequest
from app.rag.retrieval.planning.model_expansion import expand_model_queries
class Model:
    model_name = 'test-model'
    def __init__(self, response): self.response = response
    def invoke(self, *, query): return self.response
class Models:
    def multi_query(self, **kwargs): return Model('["alternate"]')
    def hyde(self, **kwargs): return Model('hypothesis')
    def step_back(self, **kwargs): return Model('broader')
    def decompose(self, **kwargs): return Model('["part query"]')
settings = ModelQuerySettings(MultiQuerySettings(True,2,0.0,400,MultiQueryExperiment(None,None,None,False)),TextQuerySettings(True,0.0,400,400),TextQuerySettings(True,0.0,400,400),DecompositionSettings(True,2,0,400,0.0,False,True))
result = expand_model_queries(ModelQueryRequest('base','hybrid',settings),models=Models())
assert result.multi_query.queries == ['alternate'] and result.hyde.text == 'hypothesis'
assert result.step_back.text == 'broader' and result.decomposition.queries == ['part query']
assert 'app.rag.retrieval.orchestrator' not in sys.modules
assert 'app.rag.runtime.engine' not in sys.modules and 'app.rag.retrieval.recall.retriever' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
