import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from threading import Barrier

import pytest
from langchain_core.documents import Document


def _doc(key, score=0.8, *, family=None):
    return Document(
        id=key,
        page_content=key,
        metadata={"chunk_id": key, "score": score, "hierarchy_family_key": family},
    )


def _settings(*, top_k=3, budget=1, hierarchy=False):
    from app.rag.retrieval.planning.normalization import HierarchyContractSettings
    from app.rag.retrieval.ranking.queries import QueryFusionSettings

    return QueryFusionSettings(
        top_k,
        60,
        True,
        budget,
        HierarchyContractSettings(hierarchy, True, "frequency", False, 0, 0, 1),
    )


def _batch(*groups):
    from app.rag.retrieval.ranking.queries import QueryCandidateGroup

    return tuple(QueryCandidateGroup(kind, docs) for kind, docs in groups)


def test_fusion_keeps_single_query_and_empty_results_without_claiming_diversification():
    from app.rag.retrieval.ranking.queries import fuse_query_candidates

    empty = fuse_query_candidates(_batch(), settings=_settings())
    one = fuse_query_candidates(_batch(("main", [_doc("one")])), settings=_settings())
    assert empty.documents == [] and empty.refill_documents == []
    assert [doc.id for doc in one.documents] == ["one"]
    assert "query_expansion_fused" not in one.documents[0].metadata
    assert one.family_metadata == {"enabled": False, "reason": "not_run"}
    assert one.diversity.used is False and one.failures == ()


def test_fusion_preserves_rrf_hits_stable_order_and_caller_documents():
    from app.rag.retrieval.ranking.queries import fuse_query_candidates

    a, b, c = _doc("a", 0.9), _doc("b", 0.8), _doc("c", 0.7)
    batch = _batch(("main", [a, b]), ("alias", [b, c]), ("mq", [c]))
    original = deepcopy([doc.metadata for doc in (a, b, c)])
    result = fuse_query_candidates(batch, settings=_settings(budget=0))
    assert [doc.id for doc in result.documents] == ["b", "c", "a"]
    assert result.documents[0].metadata["query_expansion_hits"] == 2
    assert [doc.metadata for doc in (a, b, c)] == original
    assert result.diversity.budget == 0 and result.diversity.used is False


def test_diversification_reserves_the_requested_multi_query_share():
    from app.rag.retrieval.ranking.queries import fuse_query_candidates

    result = fuse_query_candidates(
        _batch(("main", [_doc("a", 0.9), _doc("b"), _doc("c")]), ("mq", [_doc("d", 0.6)])),
        settings=_settings(),
    )
    assert [doc.id for doc in result.documents] == ["a", "b", "d"]
    assert result.diversity.used is True
    assert (result.diversity.selected_non_mq, result.diversity.selected_mq, result.diversity.fill_from_fused) == (
        2,
        1,
        0,
    )
    assert {doc.id for doc in result.refill_documents} == {"a", "b", "c", "d"}


def test_diversification_deduplicates_shared_hits_and_refills_the_remaining_slots():
    from app.rag.retrieval.ranking.queries import fuse_query_candidates

    a, b, c = _doc("a"), _doc("b"), _doc("c")
    result = fuse_query_candidates(_batch(("main", [a]), ("mq", [a, b, c])), settings=_settings())
    assert [doc.id for doc in result.documents] == ["a", "b", "c"]
    assert (result.diversity.selected_non_mq, result.diversity.selected_mq, result.diversity.fill_from_fused) == (
        1,
        1,
        1,
    )


def test_family_frequency_reorders_fusion_while_retaining_the_original_refill_pool():
    from app.rag.retrieval.ranking.queries import fuse_query_candidates

    result = fuse_query_candidates(
        _batch(
            ("main", [_doc("a", 0.9, family="A"), _doc("b", 0.8, family="B")]), ("alias", [_doc("c", 0.7, family="B")])
        ),
        settings=_settings(hierarchy=True, budget=0),
    )
    assert [doc.id for doc in result.documents] == ["b", "c", "a"]
    assert [doc.id for doc in result.refill_documents] == ["a", "c", "b"]
    assert result.family_metadata["enabled"] is True and result.family_metadata["families"] == 2


@pytest.mark.parametrize("stage", ["family_features", "family_aggregation"])
def test_optional_family_failure_keeps_candidates_and_the_original_exception(monkeypatch, stage):
    from app.rag.retrieval.ranking import hierarchy
    from app.rag.retrieval.ranking.queries import fuse_query_candidates

    failure = ValueError(stage)

    def broken(*args, **kwargs):
        raise failure

    target = "_build_hierarchy_family_features" if stage == "family_features" else "_apply_hierarchy_family_aggregation"
    monkeypatch.setattr(hierarchy, target, broken)
    result = fuse_query_candidates(
        _batch(("main", [_doc("a", family="A")]), ("alias", [_doc("b", family="B")])),
        settings=_settings(hierarchy=True, budget=0),
    )
    assert {doc.id for doc in result.documents} == {"a", "b"}
    assert result.failures[0].stage == stage and result.failures[0].error is failure
    assert result.family_metadata["enabled"] is False


def test_mandatory_fusion_error_propagates_without_fabricating_empty_success(monkeypatch):
    from app.rag.retrieval.ranking import queries as candidate_ranking
    from app.rag.retrieval.ranking.queries import fuse_query_candidates

    failure = ValueError("invalid fusion input")

    def broken(*args, **kwargs):
        raise failure

    monkeypatch.setattr(candidate_ranking, "fuse_docs_rrf", broken)
    with pytest.raises(ValueError) as caught:
        fuse_query_candidates(_batch(("main", [_doc("a")]), ("alias", [_doc("b")])), settings=_settings())
    assert caught.value is failure


def test_optional_diversity_family_failure_retains_partial_order_and_original_error(monkeypatch):
    from app.rag.retrieval.ranking import hierarchy
    from app.rag.retrieval.ranking.queries import fuse_query_candidates

    failure = ValueError("multi-query family aggregation unavailable")
    original = hierarchy._apply_hierarchy_family_aggregation
    calls = 0

    def aggregate(documents, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise failure
        return original(documents, **kwargs)

    monkeypatch.setattr(hierarchy, "_apply_hierarchy_family_aggregation", aggregate)
    result = fuse_query_candidates(
        _batch(("main", [_doc("a", family="A"), _doc("b", family="A")]), ("mq", [_doc("c", family="C")])),
        settings=_settings(hierarchy=True),
    )
    assert {doc.id for doc in result.documents} == {"a", "b", "c"}
    assert result.diversity.used and calls == 3
    assert result.failures[0].stage == "diversity_family_aggregation" and result.failures[0].error is failure


def test_actual_fusion_executes_with_engine_orchestrator_and_reader_imports_blocked():
    script = r"""
import importlib.abc
import sys

class BlockRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"app.rag.runtime.engine", "app.rag.retrieval.recall.retriever", "app.rag.retrieval.orchestrator"}:
            raise AssertionError("fusion imported an upper runtime: " + fullname)

sys.meta_path.insert(0, BlockRuntime())
from langchain_core.documents import Document
from app.rag.retrieval.ranking.queries import (
    QueryCandidateGroup, QueryFusionSettings, fuse_query_candidates,
)
from app.rag.retrieval.planning.normalization import HierarchyContractSettings
docs = [Document(id=key, page_content=key, metadata={"chunk_id": key}) for key in ("a", "b")]
result = fuse_query_candidates(
    (QueryCandidateGroup("main", docs[:1]), QueryCandidateGroup("mq", docs[1:])),
    settings=QueryFusionSettings(2, 60, True, 1, HierarchyContractSettings(False, False, "combined", False, 0, 0, 1)),
)
assert [doc.id for doc in result.documents] == ["a", "b"]
assert result.diversity.used and not result.failures
print("actual query fusion executed")
"""
    result = subprocess.run([sys.executable, "-X", "utf8", "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "actual query fusion executed"


def test_concurrent_fusion_results_keep_their_own_candidates_and_diagnostics(monkeypatch):
    from app.rag.retrieval.ranking import hierarchy
    from app.rag.retrieval.ranking.queries import fuse_query_candidates

    gate = Barrier(2)
    original = hierarchy._build_hierarchy_family_features

    def overlap(groups):
        gate.wait(timeout=5)
        return original(groups)

    monkeypatch.setattr(hierarchy, "_build_hierarchy_family_features", overlap)
    options = _settings(hierarchy=True)

    def execute(prefix, budget):
        return fuse_query_candidates(
            _batch(
                ("main", [_doc(prefix + "a", family=prefix), _doc(prefix + "b", family=prefix)]),
                ("mq", [_doc(prefix + "c", family=prefix)]),
            ),
            settings=replace(options, multi_query_budget=budget),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(execute, "first-", 1)
        second = pool.submit(execute, "second-", 0)
        first, second = first.result(), second.result()
    assert all(doc.id.startswith("first-") for doc in first.documents)
    assert all(doc.id.startswith("second-") for doc in second.documents)
    assert first.diversity.used is True and second.diversity.used is False
    assert first.family_metadata is not second.family_metadata


def test_public_retrieval_consumes_the_owned_fusion_result(monkeypatch):
    from app.infrastructure.config import settings
    from app.query import expand
    from app.rag.retrieval import orchestrator
    from app.rag.retrieval.planning import model_expansion as model_query_expansion
    from app.rag.retrieval.planning.contracts import QueryListOutcome
    from app.rag.retrieval.ranking import queries as candidate_ranking
    from app.rag.retrieval.stages import preparation

    for flag in (
        "ENABLE_QUERY_REWRITE",
        "ENABLE_HYDE",
        "ENABLE_STEP_BACK_QUERY",
        "ENABLE_QUERY_DECOMPOSITION",
        "RETRIEVAL_LIGHTWEIGHT_SUBQUERY_ENABLED",
        "RAG_TEMPORAL_INTENT_ENABLED",
        "EVIDENCE_POST_RERANK_ENABLED",
        "KG_ENABLED",
        "KG_CHAT_ENABLED",
        "RAG_EVIDENCE_REQUIRE_SPANS_ENABLED",
    ):
        monkeypatch.setattr(settings, flag, False)
    monkeypatch.setattr(settings, "MULTI_QUERY_DIVERSIFY_ENABLED", True)
    monkeypatch.setattr(settings, "MULTI_QUERY_DIVERSIFY_BUDGET", 1)
    monkeypatch.setattr(settings, "RETRIEVAL_CONTRACT_MODE", "")
    monkeypatch.setattr(expand, "load_base_dictionary_rules", lambda: {})
    monkeypatch.setattr(
        model_query_expansion,
        "generate_multi_queries",
        lambda *args, **kwargs: QueryListOutcome(True, ["variation"], 0.0, None, {"ok": True}),
    )

    class Retriever:
        _last_debug_metrics = {}

        def model_copy(self, **kwargs):
            return self

        def invoke(self, query):
            return [_doc("d", 0.6)] if query == "variation" else [_doc("a", 0.9), _doc("b"), _doc("c")]

    monkeypatch.setattr(preparation, "hybrid_retriever", Retriever())
    original = candidate_ranking.fuse_query_candidates
    outcomes = []

    def capture(batch, *, settings):
        result = original(batch, settings=settings)
        outcomes.append(result)
        return result

    monkeypatch.setattr(candidate_ranking, "fuse_query_candidates", capture)
    result = orchestrator.run_retrieval(
        {
            "question": "base question",
            "history": [],
            "top_k": 3,
            "metrics": {},
            "enable_multi_query": True,
            "intent_router": False,
            "adaptive_router": False,
            "enable_query_alias_expansion": False,
            "enable_kg_query_expansion": False,
            "enable_hierarchy_recall": False,
            "retrieval_profile": None,
            "must_recall": False,
        }
    )
    assert len(outcomes) == 1
    assert [doc.id for doc in result["docs"]] == ["a", "b", "d"]
    assert result["metrics"]["multi_query_diversify_used"] == outcomes[0].diversity.used
    assert result["metrics"]["multi_query_diversify_selected_non_mq"] == 2


@pytest.mark.asyncio
async def test_standard_fusion_uses_the_same_owner_without_engine_helpers(monkeypatch):
    from app.infrastructure.config import settings
    from app.query import expand
    from app.rag.runtime.streaming import query as standard_stream_query
    from app.rag.runtime.streaming import retrieval as standard_stream_retrieval
    from tests.test_standard_query_ownership import NoModuleCollaborators, _runtime

    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False)
    monkeypatch.setattr(settings, "MULTI_QUERY_DIVERSIFY_ENABLED", True)
    monkeypatch.setattr(settings, "MULTI_QUERY_DIVERSIFY_BUDGET", 1)
    monkeypatch.setattr(expand, "load_base_dictionary_rules", lambda: {})
    runtime = _runtime(
        retrieval_profile=None,
        top_k=3,
        enable_hyde=False,
        enable_query_decomposition=False,
        enable_hierarchy_recall=True,
        hierarchy_family_collapse=True,
    )
    await standard_stream_query.prepare_query_plan(runtime)
    runtime.engine = NoModuleCollaborators()
    runtime.data.docs_by_query_kinds = ["main", "mq"]
    runtime.data.docs_by_query = [
        [_doc("a", 0.9, family="A"), _doc("b", family="B"), _doc("c", family="B")],
        [_doc("d", 0.6, family="B")],
    ]
    runtime.data.mq_diversify_enabled = True
    runtime.data.mq_diversify_budget = 1
    runtime.data.mq_diversify_fill_from_fused = 0
    await standard_stream_retrieval.fuse_retrieval_results(runtime)
    assert [doc.id for doc in runtime.data.docs] == ["a", "b", "d"]
    assert runtime.data.mq_diversify_used is True
