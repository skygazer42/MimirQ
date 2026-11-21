from uuid import uuid4

import pytest
from langchain_core.documents import Document


@pytest.fixture
def retrieval(monkeypatch):
    from app.infrastructure.config import settings
    from app.query import expand
    from app.rag.retrieval import orchestrator
    from app.rag.retrieval.planning import model_expansion as model_query_expansion
    from app.rag.retrieval.planning import planner as query_planning
    from app.rag.retrieval.planning.contracts import QueryListOutcome
    from app.rag.retrieval.stages import followup as followup_stage
    from app.rag.retrieval.stages import preparation as preparation_stage
    from app.rag.retrieval.stages import requirements as requirements_stage

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
    monkeypatch.setattr(settings, "RETRIEVAL_CONTRACT_MODE", "")
    monkeypatch.setattr(expand, "load_base_dictionary_rules", lambda: {})
    monkeypatch.setattr(
        model_query_expansion,
        "generate_multi_queries",
        lambda *args, **kwargs: QueryListOutcome(True, ["alternate query"], 0.0, "local", {"ok": True}),
    )

    class Retriever:
        _last_debug_metrics = {}

        def model_copy(self, **kwargs):
            return self

        def invoke(self, query):
            return [
                Document(
                    id=query,
                    page_content=query,
                    metadata={
                        "document_id": str(uuid4()),
                        "chunk_id": query,
                        "score": 0.9,
                    },
                )
            ]

    retriever_port = Retriever()
    monkeypatch.setattr(preparation_stage, "hybrid_retriever", retriever_port, raising=True)
    monkeypatch.setattr(followup_stage, "hybrid_retriever", retriever_port, raising=True)
    monkeypatch.setattr(requirements_stage, "hybrid_retriever", retriever_port, raising=True)
    plans = []
    prepare = query_planning.prepare_query_plan

    def capture(request, *, models):
        plan = prepare(request, models=models)
        plans.append(plan)
        return plan

    monkeypatch.setattr(preparation_stage, "prepare_query_plan", capture)

    def run():
        return orchestrator.run_retrieval(
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

    return run, plans


def test_actual_retrieval_uses_plan_without_legacy_query_state_copies(monkeypatch, retrieval):
    from app.rag.retrieval import orchestrator

    original = orchestrator.RetrievalRuntimeState

    class Runtime(original):
        def __setattr__(self, name, value):
            if name in {
                "query_for_retrieval",
                "rewrite_used",
                "multi_queries",
                "alias_queries",
                "retrieval_contract_policy",
                "hierarchy_recall_enabled",
            }:
                raise AssertionError("copied owned query field back into runtime: " + name)
            super().__setattr__(name, value)

    monkeypatch.setattr(orchestrator, "RetrievalRuntimeState", Runtime)
    run, plans = retrieval
    result = run()
    assert result["query_for_retrieval"] == plans[0].query == "base question"
    assert result["query_debug"]["rewrite_used"] is False
    assert result["metrics"]["multi_query_used"] is True


def test_trace_consumes_the_same_plan_instead_of_another_query_field_mapping(monkeypatch, retrieval):
    from app.rag.retrieval.stages import tracing

    original = tracing.build_retrieval_trace
    run, plans = retrieval

    def trace_input(runtime):
        assert runtime.query_plan is plans[0]
        return original(runtime)

    monkeypatch.setattr(tracing, "build_retrieval_trace", trace_input)
    result = run()
    assert result["retrieval_trace"]["expansions"]["multi_query"]["used"] is True
    assert result["retrieval_trace"]["rewrite"]["used"] is False
