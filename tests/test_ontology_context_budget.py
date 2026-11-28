import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.infrastructure.tokens import num_tokens_from_string
from app.rag.retrieval.evidence.citations import build_citations_from_docs, filter_citations_for_context
from app.rag.runtime.graph import context as context_module
from app.rag.runtime.streaming import evidence as streaming_evidence


@pytest.fixture
def context_limits(monkeypatch):
    monkeypatch.setattr(settings, "RAG_CONTEXT_MAX_TOTAL_CHARS", 1800)
    monkeypatch.setattr(settings, "RAG_CONTEXT_MAX_TOTAL_TOKENS", 0)
    monkeypatch.setattr(settings, "RAG_CONTEXT_MAX_CHARS_PER_CHUNK", 1000)
    monkeypatch.setattr(settings, "RAG_CONTEXT_MAX_TOKENS_PER_CHUNK", 0)
    monkeypatch.setattr(settings, "RAG_CONTEXT_EVIDENCE_ENABLED", False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_COMPRESSION_ENABLED", False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_LLM_COMPRESSION_ENABLED", False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_REORDER_ENABLED", False)
    monkeypatch.setattr(context_module, "_denoise_context_docs", lambda docs: docs)


def source_document(label, content, **metadata):
    return Document(
        id=str(uuid4()),
        page_content=content,
        metadata={
            "document_id": str(uuid4()),
            "chunk_id": str(uuid4()),
            "pipeline_hash": "published-v1",
            "source": label,
            **metadata,
        },
    )


def test_rule_evaluation_time_is_distinct_from_the_fact_time(context_limits):
    context = {
        "ontology_version_id": str(uuid4()),
        "rule": {
            "rule": "accepted",
            "outcome": "true",
            "observed_at": "2026-11-27T12:00:00Z",
            "evidence": {"attributes": {"customer_accepted": 1, "recovered_at": "2026-11-11T06:15"}},
        },
    }
    result = context_module.build_grounded_context([], ontology_context=context)
    assert '"evaluation_reference_at": "2026-11-27T12:00:00Z"' in result.text
    assert '"observed_at":' not in result.text
    assert '"recovered_at": "2026-11-11T06:15"' in result.text
    assert '"customer_accepted": 1' in result.text
    assert context["rule"]["observed_at"] == "2026-11-27T12:00:00Z"


def test_ontology_response_guidance_is_a_trusted_system_message():
    from langchain_core.prompts import ChatPromptTemplate

    prompt = ChatPromptTemplate.from_template("Context: {context}\nQuestion: {question}")
    from app.rag.llm.prompts.templates import with_answer_semantics_system_message

    guided = with_answer_semantics_system_message(prompt)
    messages = guided.format_messages(context="eligible amount: 300", question="How much can be paid?")

    assert messages[0].type == "system"
    assert "Do not append records, backups, incidents, or advice merely because they share domain terms" in messages[0].content
    assert "Answer each distinct requested amount or status separately" in messages[0].content
    assert "give each as a separate labeled value" in messages[0].content
    assert "use the computed payable amount for 可支付" in messages[0].content
    assert "do not replace it with an actual-paid status" in messages[0].content
    assert messages[1].type == "human"
    assert "eligible amount: 300" in messages[1].content


@pytest.mark.parametrize("ontology_context", [False, True])
def test_generation_chain_applies_answer_scope_only_to_ontology_results(ontology_context):
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.runnables import RunnableLambda
    from app.rag.runtime.graph.generation import _build_generation_chain

    engine = SimpleNamespace(prompt_template=ChatPromptTemplate.from_template("Context: {context}\nQuestion: {question}"))
    chain = _build_generation_chain(
        engine=engine,
        llm=RunnableLambda(lambda _messages: "answer"),
        prompt_content=None,
        ontology_context=ontology_context,
    )
    messages = chain.steps[0].format_messages(context="payment database", question="What happened?")
    system_messages = [message.content for message in messages if message.type == "system"]

    assert any("Stay within the user's requested subject and scope" in message for message in system_messages) is ontology_context


def test_computed_query_and_its_policy_precede_supplementary_mentions(context_limits, monkeypatch):
    from app.rag.kg.enterprise_ontology.consumption import (
        OntologyAnswer,
        OntologyCitation,
        OntologyQuestion,
        QuestionPlan,
    )
    from app.rag.kg.enterprise_ontology.queries import NamedQueryResult
    from app.rag.kg.extraction.evidence import EvidenceSpan
    from app.services.chat import enterprise_ontology as chat
    from tests.test_enterprise_ontology_fusion import query_definition

    monkeypatch.setattr(settings, "RAG_CONTEXT_MAX_TOTAL_CHARS", 5000)
    monkeypatch.setattr(settings, "RAG_CONTEXT_MAX_CHARS_PER_CHUNK", 0)
    dataset, version, workbook, policy_id = (uuid4() for _ in range(4))
    definition = query_definition("fixture")
    definition.named_queries["total"].sources = [policy_id]
    policy_text = "按完整授权订单台账汇总，取消订单不计入。" + "计数制度。" * 100
    policy = SimpleNamespace(
        id=policy_id,
        dataset_id=dataset,
        archived_at=None,
        publication_status="published",
        filename="汇总制度.md",
    )
    policy_chunk = SimpleNamespace(id=uuid4(), content=policy_text, page_number=1)
    monkeypatch.setattr(chat, "published_version", lambda *_args: SimpleNamespace(definition=definition.model_dump()))
    monkeypatch.setattr(chat, "load_document_chunks", lambda *_a, **_k: (policy, "v1", [policy_chunk]))
    supplement = "对象的补充提及。" * 160
    query = NamedQueryResult(
        query="total",
        label="完整授权总额",
        description="按完整授权台账核算的结果。",
        parameters={},
        columns=["amount"],
        rows=[[42]],
        complete=True,
        document_ids=[workbook],
        asset_ids=["fixture"],
        sql="SELECT 42",
    )
    answer = OntologyAnswer(
        ontology_version_id=version,
        plan=QuestionPlan(query_ids=["total"]),
        queries=[query],
        answer="核算完成。",
        citations=[
            OntologyCitation(
                document_id=workbook,
                filename="对象补充.md",
                pipeline_hash="v1",
                chunk_id=uuid4(),
                page=1,
                evidence=EvidenceSpan(quote=supplement, start_char=0, end_char=len(supplement), source="quote"),
            )
        ],
    )
    turn = chat.OntologyChatTurn(answer=answer, query=OntologyQuestion(question="核对授权总额。"))
    evidence = chat.build_ontology_evidence(
        None,
        tenant_id=uuid4(),
        account_id="reader",
        dataset_ids=[dataset],
        document_ids=None,
        turn=turn,
    )
    raw = [source_document(f"普通材料 {index}", "普通检索材料。" * 90) for index in range(4)]
    context = context_module.build_grounded_context([*raw, *evidence.documents], ontology_context=evidence.context)
    assert '"amount": 42' in context.text
    assert policy_text in context.text
    assert len(context.text) <= 5000


@pytest.mark.parametrize("unit", ["characters", "tokens"])
def test_shared_budget_keeps_document_and_atomic_ontology_evidence(context_limits, monkeypatch, unit):
    if unit == "tokens":
        monkeypatch.setattr(settings, "RAG_CONTEXT_MAX_TOTAL_TOKENS", 500)
    policy = source_document("餐宿制度", "天气延误提供饮水和信息协助，航空公司原因达到门槛后提供餐宿。")
    observations = {
        "ontology_version_id": str(uuid4()),
        "object": {"object_type": "flight", "key": {"flight_id": "CF-1"}, "attributes": {"delay": 10}},
        "unavailable": ["未能核实 " + "extra data " * 1500],
    }

    result = context_module.build_grounded_context([policy], ontology_context=observations, query="CF-1 的餐宿？")

    assert policy.page_content in result.text
    assert '"flight_id": "CF-1"' in result.text
    assert "extra data" not in result.text
    measured = num_tokens_from_string(result.text) if unit == "tokens" else len(result.text)
    assert measured <= result.trace["limit"]
    assert result.trace["unit"] == unit
    assert result.trace["used"] == measured
    assert any(row["reason"] == "budget_exceeded" for row in result.trace["records"])


@pytest.mark.asyncio
async def test_stream_and_ordinary_fusion_use_identical_context(context_limits):
    doc = source_document("工单台账", "工单 WO-1 对应设备 E-6。")
    ontology = {
        "ontology_version_id": str(uuid4()),
        "object": {
            "object_type": "equipment",
            "key": {"id": "E-6"},
            "attributes": {"name": "登机桥"},
        },
    }
    expected = context_module.build_grounded_context([doc], ontology_context=ontology, query="WO-1", kg_context="")
    runtime = SimpleNamespace(
        data=SimpleNamespace(
            docs=[doc],
            ontology_context=ontology,
            ontology_metrics={},
            query_for_retrieval="WO-1",
            kg_context="",
            chunk_context="",
            retrieval_elapsed=0.01,
            mode_used="hybrid",
            citations=build_citations_from_docs(
                [doc], retrieval_elapsed_sec=0.01, retrieval_mode="hybrid", query="WO-1"
            ),
        )
    )

    await streaming_evidence.build_chunk_context(runtime)
    await streaming_evidence.join_context_sections(runtime)

    assert runtime.data.context == expected.text
    assert runtime.data.ontology_metrics["generation_context"] == expected.trace
    assert doc.metadata["document_id"] in runtime.data.context
    assert doc.metadata["chunk_id"] in runtime.data.context
    assert "published-v1" in runtime.data.context


def test_named_query_result_is_kept_whole_or_omitted(context_limits):
    data = {"query": "compare", "columns": ["id", "amount"], "rows": [["PO-1", 10], ["PO-2", 20]]}
    result_doc = source_document(
        "订单对照",
        json.dumps(data),
        ontology_evidence=True,
        ontology_observation=True,
        ontology_version_id="v1",
        ontology_kind="query",
    )
    copy = result_doc.model_copy(deep=True)

    result = context_module.build_grounded_context(
        [result_doc, copy],
        ontology_context={"ontology_version_id": "v1"},
        query="核对 PO-1 和 PO-2",
    )

    assert result.text.count(result_doc.page_content) == 1
    assert result_doc.page_content in result.text
    assert any(row["reason"] == "duplicate" for row in result.trace["records"])


def test_fact_identity_stays_separate_from_unlinked_source(context_limits):
    unrelated = source_document("早班交接", "7 号桥的维修已完成，设备 E-7。")
    ontology = {
        "ontology_version_id": "v1",
        "object": {
            "object_type": "equipment",
            "key": {"id": "E-6"},
            "asset_id": "unbound:equipment",
        },
    }

    result = context_module.build_grounded_context([unrelated], ontology_context=ontology, query="E-6")

    assert '"id": "E-6"' in result.text and "设备 E-7" in result.text
    records = result.trace["records"]
    source = next(row for row in records if row.get("chunk_id") == unrelated.metadata["chunk_id"])
    assert source["origin"] == "documents"
    assert "business_key" not in source
    assert "Co-mentions do not establish identity or a relation" in result.text


def test_budget_filter_preserves_the_existing_citation_gate(context_limits):
    selected = source_document("现行制度", "允许的当前制度。")
    removed = source_document("另一份制度", "没有入选模型上下文的材料。")
    approved = build_citations_from_docs([selected, removed], retrieval_elapsed_sec=0, retrieval_mode="hybrid")

    visible = filter_citations_for_context(approved, [selected], retrieval_mode="hybrid")

    assert [row["document_id"] for row in visible] == [selected.metadata["document_id"]]
    assert filter_citations_for_context([], [selected], retrieval_mode="hybrid") == []


def test_query_is_omitted_when_its_policy_cannot_enter_context(context_limits, monkeypatch):
    monkeypatch.setattr(settings, "RAG_CONTEXT_MAX_CHARS_PER_CHUNK", 0)
    policy = source_document("付款制度", "policy details " * 1500, ontology_evidence=True)
    computed = source_document(
        "付款计算",
        '{"columns":["payable"],"rows":[[20]]}',
        ontology_evidence=True,
        ontology_observation=True,
        ontology_policy_sources=[policy.metadata["document_id"]],
    )
    original = source_document("订单记录", "采购单 PO-1 的合同金额为 20 元。")

    result = context_module.build_grounded_context(
        [original, computed, policy],
        ontology_context={"ontology_version_id": "v1"},
        query="PO-1 本次可付多少？",
    )

    assert original.page_content in result.text
    assert computed.page_content not in result.text
    assert any(row["reason"] == "policy_source_not_selected" for row in result.trace["records"])


def test_zero_context_limit_includes_all_complete_observations(context_limits, monkeypatch):
    monkeypatch.setattr(settings, "RAG_CONTEXT_MAX_TOTAL_CHARS", 0)
    context = {"ontology_version_id": "v1", "object": {"key": {"id": "A"}}, "unavailable": ["待核实。"]}

    result = context_module.build_grounded_context([], ontology_context=context)

    assert '"id": "A"' in result.text and "待核实" in result.text
    assert result.trace["limit"] == 0
    assert all(row["in_context"] for row in result.trace["records"])


def test_source_provenance_accepts_database_uuid_identifiers(context_limits):
    document_id, chunk_id = uuid4(), uuid4()
    doc = source_document("原始工单", "工单 WO-1 对应 E-6。", document_id=document_id, chunk_id=chunk_id)

    result = context_module.build_grounded_context([doc], ontology_context={"ontology_version_id": "v1"})

    assert str(document_id) in result.text and str(chunk_id) in result.text
    assert result.trace["records"][0]["document_id"] == str(document_id)
    json.dumps(result.trace)
