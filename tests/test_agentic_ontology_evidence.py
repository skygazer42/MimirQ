import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.documents import Document

from app.rag.agents.rag_agent import AgenticRAGRunner, _AgenticGenerationState, _AgenticRetrievalState


def test_agent_document_merge_uses_shared_identity_without_engine_helpers():
    source = {"document_id": str(uuid4()), "chunk_index": 3}
    first = Document(id="first", page_content="同一文档块。", metadata=source)
    second = Document(id="second", page_content="同一文档块。", metadata=source)

    assert AgenticRAGRunner(object())._merge_docs([first], [second]) == [first]


def test_parallel_agent_document_merge_uses_shared_preference_without_engine_helpers():
    from app.rag.agents.multi_agent import MultiAgentRAGRunner

    source = {"document_id": str(uuid4()), "chunk_index": 3}
    first = Document(id="first", page_content="较低分原文。", metadata={**source, "score": 0.1})
    second = Document(id="second", page_content="较高分原文。", metadata={**source, "score": 0.9})
    results = [
        SimpleNamespace(index=index, elapsed_sec=0.1, result={"docs": [doc], "metrics": {}, "citations": []})
        for index, doc in enumerate((first, second))
    ]

    docs, _citations, _mode, _elapsed = MultiAgentRAGRunner(object())._collect_retrieval_outputs(
        results=results, retrieval_mode="hybrid", question="原文"
    )
    assert docs == [second]


@pytest.mark.asyncio
async def test_agent_prepares_original_question_once_and_preserves_the_trusted_scope(monkeypatch):
    from app.rag.agents import rag_agent
    from app.services.chat.enterprise_ontology import OntologyEvidence

    tenant, dataset, document = uuid4(), uuid4(), uuid4()
    context = {"ontology_version_id": str(uuid4()), "object": {"key": {"id": "WO-1"}}}
    evidence = OntologyEvidence(context=context, documents=[], metrics={"ontology_used": True}, action_proposal=None)
    calls = []

    async def offload(_operation, *, request_db, **scope):
        calls.append(scope)
        return evidence

    monkeypatch.setattr(rag_agent, "run_blocking_retrieval_call_with_managed_session", offload)
    request = rag_agent.AgenticStreamRequest(
        question="核对 WO-1，准备提交验收备注。",
        ontology_enabled=True,
        tenant_id=tenant,
        account_id="reader",
        dataset_id=dataset,
        document_ids=[document],
    )

    prepared = await rag_agent.prepare_agentic_ontology(request)
    prepared_again = await rag_agent.prepare_agentic_ontology(prepared)
    state = rag_agent.build_agentic_rag_state(prepared_again, history=[])

    assert len(calls) == 1
    assert calls[0]["question"] == request.question
    assert calls[0]["tenant_id"] == tenant and calls[0]["account_id"] == "reader"
    assert calls[0]["dataset_id"] == dataset and calls[0]["document_ids"] == [document]
    assert state["ontology_prepared"] is True
    assert state["ontology_context"] == context
    assert state["metrics"]["ontology_used"] is True


def test_agentic_answer_keeps_ontology_receipt_for_history_access_recheck():
    receipt = {"version_id": "published-version", "digest": "verified-evidence"}
    context = {"used": 200, "records": [{"business_key": {"id": "private-order"}, "in_context": True}]}
    retrieval = _AgenticRetrievalState(
        final_result={
            "docs": [],
            "citations": [],
            "metrics": {
                "ontology_used": True,
                "ontology_fusion": receipt,
                "generation_context": context,
            },
        }
    )

    metrics = AgenticRAGRunner._build_metrics(
        t_start=time.time(),
        retrieval_mode="hybrid",
        complexity_score=2.0,
        threshold=1.0,
        model_route="balanced",
        plan_steps=[],
        max_rounds=1,
        retrieval_state=retrieval,
        generation_state=_AgenticGenerationState(),
    )

    assert metrics["ontology_used"] is True
    assert metrics["ontology_fusion"] == receipt
    assert metrics["generation_context"] == context


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
async def test_agent_stream_preserves_budget_action_and_history_protection(monkeypatch, parallel):
    from app.api.schemas.conversations.chat import OntologyActionProposal
    from app.infrastructure import tokens
    from app.rag.agents import multi_agent, rag_agent
    from app.services.chat.enterprise_ontology import (
        ONTOLOGY_HISTORY_PLACEHOLDER,
        OntologyEvidence,
        prepare_ontology_evidence,
        protect_fused_answer,
    )
    from tests.test_rag_agent_stream_complexity import _FakeEngine

    tenant, dataset, document, version = uuid4(), uuid4(), uuid4(), uuid4()
    proposal = OntologyActionProposal(
        ontology_id=uuid4(),
        version_id=version,
        action_id="append_note",
        label="提交备注",
        target="tickets",
        approval_required=True,
        key_fields={"id": "工单"},
        parameter_fields={},
        key={"id": "WO-1"},
        parameters={},
    )
    context = {"ontology_version_id": str(version), "object": {"key": {"id": "WO-1"}, "attributes": {"accepted": True}}}
    receipt = {"version_id": str(version), "digest": "verified-evidence"}
    evidence = OntologyEvidence(
        context=context,
        documents=[],
        metrics={"ontology_used": True, "ontology_fusion": receipt},
        action_proposal=proposal,
    )
    doc = Document(
        page_content="工单 WO-1 已验收；备注提交仍需要审批。",
        id=str(uuid4()),
        metadata={"document_id": str(document), "source": "工单制度", "score": 1.0},
    )
    prepared_questions = []

    async def offload(operation, *args, request_db, **scope):
        if operation is prepare_ontology_evidence:
            prepared_questions.append(scope["question"])
            return evidence
        return operation(object(), *args, **scope)

    def retrieve(state):
        assert state["ontology_prepared"] is True
        return {
            **state,
            "docs": [doc],
            "citations": [],
            "abstain_triggered": False,
            "metrics": {**state["metrics"], "top_relevance_score": 1.0},
        }

    async def plan(**_options):
        return [rag_agent.AgenticPlanStep(query="读取工单"), rag_agent.AgenticPlanStep(query="核对验收")]

    monkeypatch.setattr(tokens, "_get_encoder", lambda: False)
    monkeypatch.setattr(rag_agent, "run_blocking_retrieval_call_with_managed_session", offload)
    monkeypatch.setattr(multi_agent, "run_blocking_retrieval_call_with_managed_session", offload)
    monkeypatch.setattr(rag_agent, "with_answer_semantics_system_message", lambda prompt: prompt)
    monkeypatch.setattr(multi_agent, "with_answer_semantics_system_message", lambda prompt: prompt)
    monkeypatch.setattr(rag_agent, "run_retrieval", retrieve)
    monkeypatch.setattr(multi_agent, "run_retrieval", retrieve)
    for name in (
        "RAG_MULTI_AGENT_ENABLED",
        "RAG_AGENTIC_TOOLS_ENABLED",
        "RAG_CRAG_STREAMING_ENABLED",
        "RAG_SELF_RAG_ENABLED",
        "RAG_CRITIC_ENABLED",
    ):
        monkeypatch.setattr(rag_agent.settings, name, False)
    monkeypatch.setattr(rag_agent.settings, "RAG_CONTEXT_MAX_TOTAL_CHARS", 2000)
    monkeypatch.setattr(rag_agent.settings, "RAG_CONTEXT_MAX_TOTAL_TOKENS", 0)
    engine = _FakeEngine(tokens=["已准备备注，等待审批。"])
    runner = multi_agent.MultiAgentRAGRunner(engine) if parallel else rag_agent.AgenticRAGRunner(engine)
    monkeypatch.setattr(runner, "_decompose" if parallel else "_plan", plan)
    events = [
        event
        async for event in runner.stream(
            request=rag_agent.AgenticStreamRequest(
                question="为 WO-1 准备提交验收备注。",
                ontology_enabled=True,
                tenant_id=tenant,
                account_id="reader",
                dataset_id=dataset,
                document_ids=[document],
            )
        )
    ]
    done = events[-1]["data"]

    assert prepared_questions == ["为 WO-1 准备提交验收备注。"]
    assert done["ontology_action"] == proposal.model_dump(mode="json")
    assert done["metrics"]["ontology_fusion"] == receipt
    assert done["metrics"]["generation_context"]["used"] <= 2000
    assert "WO-1" in engine._captured_inputs[-1]["context"]
    assert '"accepted": true' in engine._captured_inputs[-1]["context"]
    assert len(engine._captured_inputs[-1]["context"]) <= 2000
    content, citations, protected = protect_fused_answer("已准备备注。", [], done["metrics"])
    assert content == ONTOLOGY_HISTORY_PLACEHOLDER
    assert "response" in protected["ontology_fusion"] and "generation_context" not in protected
