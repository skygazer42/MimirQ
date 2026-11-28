import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.rag.kg.enterprise_ontology import consumption
from app.rag.kg.enterprise_ontology.definition import OntologyDefinition, QueryParameter
from app.rag.kg.enterprise_ontology.queries import NamedQueryResult


def query_definition(asset_id: str) -> OntologyDefinition:
    return OntologyDefinition.model_validate(
        {
            "schema_version": 1,
            "ontology": "operations",
            "object_types": {
                "orders": {
                    "key": ["id"],
                    "properties": {"id": "string", "amount": "number", "secret": "string"},
                },
            },
            "bindings": [
                {
                    "object_type": "orders",
                    "role": "primary",
                    "asset_id": asset_id,
                    "identity_columns": ["number"],
                    "row_access_column": "visible_to",
                    "columns": {"id": "number", "amount": "total", "secret": "secret"},
                }
            ],
            "named_queries": {
                "total": {
                    "label": "授权订单总额",
                    "description": "按业务编号核对授权范围内订单总额。",
                    "objects": ["orders"],
                    "sql": "SELECT SUM(amount) AS amount FROM orders WHERE (:id IS NULL OR id = :id)",
                    "parameters": {"id": {"type": "string", "required": False}},
                },
            },
        }
    )


def test_named_query_aggregates_authorized_rows_and_cannot_read_masked_columns(tmp_path, monkeypatch):
    from app.infrastructure.config import settings
    from app.rag.kg.enterprise_ontology import queries
    from app.services.tables.store_paths import format_table_id, table_store_path

    tenant, dataset, document = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(settings, "TABLE_STORE_DIR", str(tmp_path))
    path = table_store_path(tenant_id=tenant, dataset_id=dataset, document_id=document)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE sheet_0 (number TEXT, total NUMERIC, secret TEXT, visible_to TEXT)")
        db.executemany(
            "INSERT INTO sheet_0 VALUES (?, ?, ?, ?)",
            [
                ("PO-1", 10, "private", "reader"),
                ("PO-2", 20, "private", "reader"),
                ("PO-3", 999, "private", "other"),
            ],
        )
    definition = query_definition(format_table_id(document_id=document, sheet_index=0))
    definition.named_queries["total"].parameters["id"] = QueryParameter(required=False, enum=["PO-1", "PO-2"])
    monkeypatch.setattr(
        queries,
        "authorized_snapshot",
        lambda *_a, **_kw: (
            SimpleNamespace(id=document, dataset_id=dataset, updated_at=None),
            SimpleNamespace(sql_table="sheet_0", truncated=False),
            {"number", "total", "visible_to"},
        ),
    )
    options = dict(definition=definition, tenant_id=tenant, account_id="reader", query_id="total", parameters={})
    result = queries.run_named_query(None, **options)
    assert result.rows == [[30]] and result.complete
    assert result.document_ids == [document]
    selected = queries.run_named_query(None, **{**options, "parameters": {"id": "PO-1"}})
    assert selected.parameters == {"id": "PO-1"}
    with pytest.raises(ValueError, match="enumeration"):
        queries.run_named_query(None, **{**options, "parameters": {"id": "PO-1' OR 1=1 --"}})

    outside_scope = consumption.execute_question_plan(
        None,
        definition=definition,
        version_id=uuid4(),
        tenant_id=tenant,
        account_id="reader",
        request=consumption.OntologyQuestion(question="核对总额", document_ids=[uuid4()]),
        plan=consumption.QuestionPlan(query_ids=["total"]),
    )
    assert outside_scope.queries == []
    assert outside_scope.unavailable == ["授权订单总额：无法访问查询数据来源"]

    for sql in ("SELECT secret FROM orders", "SELECT total FROM main.sheet_0", "DELETE FROM orders"):
        malicious = definition.model_copy(deep=True)
        malicious.named_queries["total"].sql = sql
        with pytest.raises((ValueError, sqlite3.DatabaseError)):
            queries.run_named_query(None, **{**options, "definition": malicious})


@pytest.mark.parametrize(
    ("explicit_value", "expected_id", "expected_amount"), [("PO-2", "PO-2", 20), ("订单一", "PO-1", 10)]
)
def test_named_query_keeps_explicit_object_parameters(monkeypatch, explicit_value, expected_id, expected_amount):
    definition = query_definition("unbound:orders")
    definition.named_queries["total"].parameters = {
        name: QueryParameter(type="string", object_type="orders") for name in ("order_id", "other_order_id")
    }
    executed_parameters = []

    def run_query(_db, *, parameters, **_options):
        executed_parameters.append(parameters)
        amounts = {"PO-1": 10, "PO-2": 20}
        return NamedQueryResult(
            query="total",
            label="订单金额对照",
            description="比较两笔授权订单",
            columns=["amount", "other_amount"],
            rows=[[amounts[parameters["order_id"]], amounts[parameters["other_order_id"]]]],
            complete=True,
            document_ids=[uuid4()],
            asset_ids=["unbound:orders"],
            sql="SELECT amount FROM orders",
        )

    monkeypatch.setattr(consumption, "run_named_query", run_query)
    result = consumption.execute_question_plan(
        None,
        definition=definition,
        version_id=uuid4(),
        tenant_id=uuid4(),
        account_id="reader",
        request=consumption.OntologyQuestion(question=f"对照订单一和 {explicit_value} 的订单金额。"),
        plan=consumption.QuestionPlan(
            object_type="orders",
            business_key="PO-1",
            object_name="订单一",
            query_ids=["total"],
            query_parameters={"total": {"other_order_id": explicit_value}},
        ),
    )

    assert executed_parameters == [{"order_id": "PO-1", "other_order_id": expected_id}]
    assert result.queries[0].rows == [[10, expected_amount]]


@pytest.mark.asyncio
async def test_named_query_plan_rejects_a_partial_object_identifier():
    definition = query_definition("unbound:orders")
    definition.named_queries["total"].parameters["id"] = QueryParameter(type="string", object_type="orders")

    class Client:
        async def chat_with_schema(self, _messages, **_kwargs):
            return {
                "object_type": "orders",
                "business_key": "PO-20",
                "query_ids": ["total"],
                "query_parameters": {"total": {"id": "PO-2"}},
            }

    request = consumption.OntologyQuestion(question="核对 PO-20 的授权总额。")
    with pytest.raises(consumption.InvalidOntologyPlanError):
        await consumption.plan_question(definition, request, Client())


@pytest.mark.asyncio
async def test_planner_repairs_an_omitted_user_named_enum_filter():
    definition = query_definition("unbound:orders")
    definition.named_queries[
        "total"
    ].sql = "SELECT COUNT(*) AS amount FROM orders WHERE (:owner_team IS NULL OR owner_team=:owner_team)"
    definition.named_queries["total"].parameters = {
        "owner_team": QueryParameter(required=False, enum=["数据组", "应用一组"]),
    }
    plans = iter(
        [
            {"query_ids": ["total"], "query_parameters": {"total": {}}},
            {"query_ids": ["total"], "query_parameters": {"total": {"owner_team": "数据组"}}},
        ]
    )

    class Client:
        calls = 0

        async def chat_with_schema(self, _messages, **_kwargs):
            self.calls += 1
            return next(plans)

    client = Client()
    plan = await consumption.plan_question(
        definition,
        consumption.OntologyQuestion(question="数据组这批工单有多少？"),
        client,
    )
    assert client.calls == 2
    assert plan.parameter_sets("total") == [{"owner_team": "数据组"}]


@pytest.mark.asyncio
async def test_planner_repairs_an_invented_timezone_before_executing_the_query():
    definition = query_definition("unbound:orders")
    definition.named_queries["total"].parameters["as_of"] = QueryParameter(type="string")
    values = iter(["2026-11-17T10:00:00+08:00", "2026-11-17T10:00"])

    class Client:
        async def chat_with_schema(self, _messages, **_kwargs):
            return {"query_ids": ["total"], "query_parameters": {"total": {"as_of": next(values)}}}

    request = consumption.OntologyQuestion(question="按2026-11-17T10:00核对订单。")
    plan = await consumption.plan_question(definition, request, Client())
    assert plan.query_parameters == {"total": {"as_of": "2026-11-17T10:00"}}


@pytest.mark.asyncio
async def test_planner_rejects_invented_parameters_after_the_single_repair():
    definition = query_definition("unbound:orders")
    values = iter(["PO-9", "PO-8"])

    class Client:
        async def chat_with_schema(self, _messages, **_kwargs):
            return {"query_ids": ["total"], "query_parameters": {"total": {"id": next(values)}}}

    request = consumption.OntologyQuestion(question="核对 PO-1 的订单金额。")
    with pytest.raises(consumption.InvalidOntologyPlanError):
        await consumption.plan_question(definition, request, Client())
    assert list(values) == []


@pytest.mark.asyncio
async def test_planning_uses_user_history_and_keeps_multiple_explicit_tasks():
    definition = query_definition("unbound:orders")
    seen = []

    class Client:
        async def chat_with_schema(self, messages, **_kwargs):
            seen.extend(messages)
            return {"object_type": "orders", "business_key": "PO-1", "query_ids": ["total"]}

    request = consumption.OntologyQuestion.model_validate(
        {
            "question": "这笔订单的授权总额是多少？",
            "history": [{"role": "user", "content": "核对采购订单 PO-1。"}],
        }
    )
    plan = await consumption.plan_question(definition, request, Client())
    assert plan.business_key == "PO-1" and plan.query_ids == ["total"]
    assert any("PO-1" in message.content for message in seen)


def test_ontology_observations_continue_through_document_retrieval(monkeypatch):
    from app.rag.retrieval import orchestrator
    from app.services.chat import enterprise_ontology

    calls = []
    original_tag = object()
    ontology_doc = object()
    evidence = enterprise_ontology.OntologyEvidence(
        context={"total": 0},
        documents=[ontology_doc],
        metrics={"ontology_used": True},
        action_proposal=None,
    )
    monkeypatch.setattr(enterprise_ontology, "prepare_ontology_evidence", lambda *_a, **_k: evidence)

    def retrieve(runtime):
        calls.append(runtime.state["ontology_context"])
        assert runtime.state["tag_docs"] == [original_tag]
        assert runtime.state["ontology_docs"] == [ontology_doc]
        return {**runtime.state, "docs": ["policy source"], "abstain_triggered": False}

    monkeypatch.setattr(orchestrator, "_RETRIEVAL_RUNTIME_PHASES", [retrieve])
    monkeypatch.setattr(orchestrator, "_run_retrieval_citations_hard_fallback_phase", retrieve)
    state = {
        "question": "依据制度计算总额",
        "ontology_enabled": True,
        "db": object(),
        "tenant_id": uuid4(),
        "account_id": "reader",
        "dataset_id": uuid4(),
        "document_ids": [],
        "tag_docs": [original_tag],
    }
    result = orchestrator.run_retrieval(state)
    assert calls == [{"total": 0}] and result["docs"] == ["policy source"]
    assert result["metrics"]["ontology_used"] is True


@pytest.mark.parametrize("rows", [[[20]], [[0]], []])
def test_ontology_prompt_injects_policy_documents_only_for_usable_queries(monkeypatch, rows):
    from app.services.chat import enterprise_ontology as chat

    tenant, dataset, version = uuid4(), uuid4(), uuid4()
    workbook, shared_source, unused_source, missing_source = uuid4(), uuid4(), uuid4(), uuid4()
    definition = query_definition("unbound:orders")
    definition.named_queries["total"].sources = [shared_source, unused_source, missing_source]
    definition.named_queries["daily"] = definition.named_queries["total"].model_copy(
        update={"sources": [shared_source]}
    )
    query = consumption.OntologyQuestion(question="核对订单金额。")
    turn = chat.OntologyChatTurn(
        query=query,
        answer=consumption.OntologyAnswer(
            ontology_version_id=version,
            plan=consumption.QuestionPlan(query_ids=["total", "daily"]),
            queries=[
                NamedQueryResult(
                    query=query_id,
                    label=query_id,
                    description="订单金额",
                    columns=["amount"],
                    rows=rows,
                    complete=True,
                    document_ids=[workbook],
                    asset_ids=["unbound:orders"],
                    sql="SELECT amount FROM orders",
                    parameters={"day": "2026-11-18"},
                )
                for query_id in ("total", "daily")
            ],
            answer="订单金额为 20。",
        ),
    )

    async def answer_from_snapshot(*_args, **_kwargs) -> chat.OntologyChatTurn:
        return turn

    def load_policy(_db, _tenant, _account, source, *, limit):
        if source == missing_source:
            raise HTTPException(status_code=404)
        return (
            SimpleNamespace(
                id=source,
                dataset_id=dataset,
                archived_at=None,
                publication_status="published",
                filename=f"{source}.md",
            ),
            "published",
            [SimpleNamespace(id=uuid4(), content="授权采购制度。", page_number=1)],
        )

    monkeypatch.setattr(chat, "active_version_id", lambda *_args: version)
    monkeypatch.setattr(chat, "answer_scoped_ontology", answer_from_snapshot)
    monkeypatch.setattr(chat, "published_version", lambda *_args: SimpleNamespace(definition=definition.model_dump()))
    monkeypatch.setattr(chat, "load_document_chunks", load_policy)
    evidence = chat.prepare_ontology_evidence(
        None, tenant_id=tenant, account_id="reader", dataset_id=dataset, document_ids=None, question=query.question
    )

    assert evidence is not None
    context = evidence.context
    assert [result["query"] for result in context["queries"]] == ["daily"]
    assert {doc.metadata["document_id"] for doc in evidence.documents} == {str(workbook), str(shared_source)}
    assert evidence.metrics["ontology_fusion"]["source_document_ids"] == sorted((str(workbook), str(shared_source)))
    data = json.loads(
        next(doc.page_content for doc in evidence.documents if doc.metadata.get("ontology_kind") == "query")
    )
    assert data["parameters"] == {"day": "2026-11-18"}
    assert data["records"] == [{"amount": row[0]} for row in rows]
    assert "columns" not in data and "rows" not in data
    assert evidence.metrics["ontology_used"] is True


def test_failed_ontology_lookup_without_observations_keeps_diagnostics_out_of_source_context(monkeypatch):
    from app.services.chat import enterprise_ontology as chat

    version = uuid4()
    query = consumption.OntologyQuestion(question="假设可结算八件、单价 560 元，扣 10% 质保金后可付多少？")
    answer = consumption.OntologyAnswer(
        ontology_version_id=version,
        plan=consumption.QuestionPlan(query_ids=["settlement"]),
        unavailable=["settlement: Missing business query parameter: order_id"],
        answer="Missing business query parameter: order_id",
    )

    async def failed_lookup(*_args, **_kwargs):
        return chat.OntologyChatTurn(answer=answer, query=query)

    monkeypatch.setattr(chat, "active_version_id", lambda *_args: version)
    monkeypatch.setattr(chat, "answer_scoped_ontology", failed_lookup)
    evidence = chat.prepare_ontology_evidence(
        None, tenant_id=uuid4(), account_id="reader", dataset_id=uuid4(), document_ids=None, question=query.question
    )

    assert evidence is not None
    assert evidence.context == {} and not evidence.documents
    assert evidence.metrics["ontology_used"] is False
    assert evidence.metrics["ontology_unavailable"] == answer.unavailable


def test_named_query_parameters_preserve_saved_evidence_receipts():
    from app.services.chat.enterprise_ontology import _evidence_digest

    result = NamedQueryResult(
        query="daily",
        label="当日统计",
        description="按给定日期汇总",
        columns=["count"],
        rows=[[0]],
        complete=True,
        document_ids=[uuid4()],
        asset_ids=["unbound:orders"],
        sql="SELECT COUNT(*) FROM orders",
        parameters={"day": "2026-11-18"},
    )
    answer = consumption.OntologyAnswer(
        ontology_version_id=uuid4(),
        plan=consumption.QuestionPlan(query_ids=["daily"], query_parameters={"daily": {"day": "2026-11-18"}}),
        queries=[result],
        answer="0",
    )
    saved = answer.model_dump(mode="json")
    saved["queries"][0].pop("parameters")
    previous_digest = hashlib.sha256(
        json.dumps(saved, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()

    assert _evidence_digest(answer) == previous_digest


def test_ontology_prompt_keeps_business_times_without_source_update_time(monkeypatch):
    from app.rag.kg.enterprise_ontology.behaviors import RuleResult
    from app.rag.kg.enterprise_ontology.objects import BusinessObject
    from app.services.chat import enterprise_ontology as chat

    tenant, dataset, version = uuid4(), uuid4(), uuid4()
    observed_at = datetime(2026, 11, 18, 2, tzinfo=UTC)
    query = consumption.OntologyQuestion(question="服务单-2520 已恢复吗？", observed_at=observed_at)
    record = BusinessObject(
        tenant_id=tenant,
        ontology="operations",
        object_type="tickets",
        namespace="tickets",
        key={"ticket_id": "服务单-2520"},
        attributes={"recovered_at": "2026-11-16T06:20"},
        asset_id="tickets",
        source_updated_at=datetime(2026, 11, 26, 8, 32, tzinfo=UTC),
    )
    answer = consumption.OntologyAnswer(
        ontology_version_id=version,
        plan=consumption.QuestionPlan(object_type="tickets", business_key="服务单-2520", include_object=True),
        object=record,
        rule=RuleResult(
            version_id=version,
            rule="ticket_customer_acceptance",
            outcome="true",
            observed_at=observed_at,
            evidence=record,
        ),
        answer="工单已恢复。",
    )

    async def answer_from_snapshot(*_args, **_kwargs) -> chat.OntologyChatTurn:
        return chat.OntologyChatTurn(answer=answer, query=query)

    monkeypatch.setattr(chat, "active_version_id", lambda *_args: version)
    monkeypatch.setattr(chat, "answer_scoped_ontology", answer_from_snapshot)
    evidence = chat.prepare_ontology_evidence(
        None, tenant_id=tenant, account_id="reader", dataset_id=dataset, document_ids=[], question=query.question
    )

    assert evidence is not None
    context = evidence.context
    assert datetime.fromisoformat(context["rule"]["observed_at"]) == observed_at
    for item in (context["object"], context["rule"]["evidence"]):
        assert item["attributes"]["recovered_at"] == "2026-11-16T06:20"
        assert "source_updated_at" not in item


def test_generated_ontology_answer_is_not_saved_as_unprotected_plaintext():
    from app.services.chat.enterprise_ontology import ONTOLOGY_HISTORY_PLACEHOLDER, protect_fused_answer

    content, citations, metrics = protect_fused_answer(
        "采购单实付为 20 元",
        [{"document_id": uuid4()}],
        {"ontology_fusion": {"digest": "verified"}, "generation_context": {"business_key": "PO-PRIVATE"}},
    )
    assert content == ONTOLOGY_HISTORY_PLACEHOLDER and citations == []
    assert "采购单" not in metrics["ontology_fusion"]["response"]
    assert "generation_context" not in metrics
    assert "PO-PRIVATE" not in str(metrics)


def test_fused_history_keeps_action_proposal_when_table_egress_is_disabled(monkeypatch):
    from app.services.chat import enterprise_ontology as chat

    tenant, dataset, source_document = uuid4(), uuid4(), uuid4()
    payload = query_definition("unbound:orders").model_dump(mode="json", by_alias=True)
    payload["actions"] = {"close": {"object_type": "orders", "target": "business", "approval_required": True}}
    definition = OntologyDefinition.model_validate(payload)
    version = SimpleNamespace(id=uuid4(), ontology_id=uuid4(), definition=payload)
    request = consumption.OntologyQuestion(question="预演关闭 PO-1", dataset_ids=[dataset])
    plan = consumption.QuestionPlan(object_type="orders", business_key="PO-1", action_id="close", query_ids=["total"])
    monkeypatch.setattr(consumption, "read_ontology_citations", lambda *_a, **_kw: ([], []))
    monkeypatch.setattr(consumption, "run_named_query", lambda *_a, **_kw: pytest.fail("Table egress is disabled"))
    monkeypatch.setattr(chat, "published_version", lambda *_a: version)
    monkeypatch.setattr(chat, "active_version_id", lambda *_a: version.id)
    monkeypatch.setattr(chat, "get_allowed_document_id_sets", lambda *_a: ({source_document}, set()))

    result = consumption.execute_question_plan(
        None,
        definition=definition,
        version_id=version.id,
        tenant_id=tenant,
        account_id="reader",
        request=request,
        plan=plan,
        documents_only=True,
    )
    turn = chat.OntologyChatTurn(answer=result, query=request, documents_only=True)
    receipt = {
        **turn.receipt_metadata["ontology_query"],
        "dataset_id": str(dataset),
        "source_document_ids": [str(source_document)],
    }
    trace = {"records": [{"business_key": "PO-1"}]}
    content, citations, metadata = chat.protect_fused_answer(
        "已生成审批提案。", [], {"ontology_fusion": receipt, "generation_context": trace}
    )
    message = SimpleNamespace(
        id=uuid4(),
        role="assistant",
        content=content,
        citations=citations,
        message_metadata=metadata,
        created_at=datetime.now(UTC),
    )
    visible = chat.visible_ontology_message(None, tenant_id=tenant, account_id="reader", message=message)
    assert visible.content == "已生成审批提案。"
    assert visible.ontology_action is not None
    assert visible.ontology_action.key == {"id": "PO-1"} and visible.ontology_action.approval_required
    assert visible.message_metadata["generation_context"] == trace

    monkeypatch.setattr(chat, "get_allowed_document_id_sets", lambda *_a: (set(), set()))
    denied = chat.visible_ontology_message(None, tenant_id=tenant, account_id="reader", message=message)
    assert "generation_context" not in denied.message_metadata
    assert denied.ontology_action is None


def test_single_query_flat_parameters_are_bound_to_the_selected_query():
    plan = consumption.QuestionPlan.model_validate(
        {
            "query_ids": ["total"],
            "query_parameters": {"id": "PO-1"},
        }
    )
    assert plan.query_parameters == {"total": {"id": "PO-1"}}


def test_one_named_query_executes_each_requested_parameter_set(monkeypatch):
    definition = query_definition("unbound:orders")
    calls = []

    def run_query(_db, *, query_id, parameters, **_scope):
        calls.append(dict(parameters))
        return NamedQueryResult(
            query=query_id,
            label="订单金额",
            description="按指定订单核算",
            parameters=parameters,
            columns=["amount"],
            rows=[[10 if parameters["id"] == "PO-1" else 20]],
            complete=True,
            document_ids=[uuid4()],
            asset_ids=["unbound:orders"],
            sql="SELECT amount FROM orders",
        )

    monkeypatch.setattr(consumption, "run_named_query", run_query)
    answer = consumption.execute_question_plan(
        None,
        definition=definition,
        version_id=uuid4(),
        tenant_id=uuid4(),
        account_id="reader",
        request=consumption.OntologyQuestion(question="分别查询 PO-1 和 PO-2。"),
        plan=consumption.QuestionPlan(
            query_ids=["total"], query_parameters={"total": [{"id": "PO-1"}, {"id": "PO-2"}]}
        ),
        require_active=False,
    )

    assert calls == [{"id": "PO-1"}, {"id": "PO-2"}]
    assert [item.parameters for item in answer.queries] == calls
    assert [item.rows for item in answer.queries] == [[[10]], [[20]]]


@pytest.mark.asyncio
@pytest.mark.parametrize("other_id", ["PO-2", "PO-20"])
async def test_every_named_query_parameter_set_is_grounded_in_the_user_request(other_id):
    definition = query_definition("unbound:orders")
    definition.named_queries["total"].parameters["id"] = QueryParameter(type="string", object_type="orders")

    class Planner:
        async def chat_with_schema(self, *_args, **_kwargs):
            return {"query_ids": ["total"], "query_parameters": {"total": [{"id": "PO-1"}, {"id": other_id}]}}

    request = consumption.OntologyQuestion(question="查询 PO-1 和 PO-2。")
    if other_id == "PO-20":
        with pytest.raises(consumption.InvalidOntologyPlanError):
            await consumption.plan_question(definition, request, Planner())
    else:
        plan = await consumption.plan_question(definition, request, Planner())
        assert plan.parameter_sets("total") == [{"id": "PO-1"}, {"id": "PO-2"}]


def test_named_query_parameter_batches_are_bounded():
    plan = consumption.QuestionPlan(query_ids=["total"], query_parameters={"total": [{"id": "PO-1"}] * 6})
    assert len(plan.parameter_sets("total")) == 6
    with pytest.raises(ValueError):
        consumption.QuestionPlan(query_ids=["total"], query_parameters={"total": [{"id": "PO-1"}] * 7})
    with pytest.raises(ValueError, match="at most six"):
        consumption.QuestionPlan(
            query_ids=["first", "second"],
            query_parameters={"first": [{"id": "PO-1"}] * 4, "second": [{"id": "PO-2"}] * 4},
        )


def test_aggregate_query_policy_citations_do_not_require_an_arbitrary_business_object(monkeypatch):
    from app.rag.kg.enterprise_ontology.preview import ChunkPreview

    tenant, dataset, version, source, chunk_id = (uuid4() for _ in range(5))
    definition = query_definition("fixture")
    definition.named_queries["total"].sources = [source]
    text = "按完整授权订单台账汇总，已取消订单不计入。"
    chunk = SimpleNamespace(id=chunk_id, content=text, page_number=1)
    preview = ChunkPreview(document_id=source, chunk_id=chunk_id, page=1)
    doc = SimpleNamespace(id=source, filename="统计口径.md", doc_metadata={"effective_at": "2026-11-01"})
    db = SimpleNamespace(execute=lambda _query: [(SimpleNamespace(pipeline_hash="published"), doc)])
    monkeypatch.setattr(consumption, "get_dataset", lambda *_args: SimpleNamespace(id=dataset))
    monkeypatch.setattr(consumption, "assert_dataset_readable", lambda *_args: None)
    monkeypatch.setattr(consumption, "active_version_id", lambda *_args: version)
    monkeypatch.setattr(consumption, "list_accessible_document_ids", lambda *_args, **_scope: [source])
    monkeypatch.setattr(consumption, "current_document_previews", lambda *_args: [(preview, chunk)])

    citations, unavailable = consumption.read_ontology_citations(
        db,
        tenant_id=tenant,
        account_id="reader",
        version_id=version,
        request=consumption.OntologyQuestion(question="汇总订单并引用口径。", dataset_ids=[dataset]),
        plan=consumption.QuestionPlan(query_ids=["total"], include_documents=True),
        definition=definition,
        observed_at=datetime(2026, 11, 18, tzinfo=UTC),
    )

    assert unavailable == []
    assert len(citations) == 1 and citations[0].document_id == source
    assert citations[0].evidence.quote == text and citations[0].applicability == "applicable"


def test_aggregate_query_citations_respect_the_explicit_document_selection(monkeypatch):
    tenant, dataset, version, source = (uuid4() for _ in range(4))
    definition = query_definition("fixture")
    definition.named_queries["total"].sources = [source]
    monkeypatch.setattr(consumption, "get_dataset", lambda *_args: SimpleNamespace(id=dataset))
    monkeypatch.setattr(consumption, "assert_dataset_readable", lambda *_args: None)
    monkeypatch.setattr(consumption, "active_version_id", lambda *_args: version)
    monkeypatch.setattr(consumption, "list_accessible_document_ids", lambda *_args, **_scope: [source])

    citations, unavailable = consumption.read_ontology_citations(
        None,
        tenant_id=tenant,
        account_id="reader",
        version_id=version,
        request=consumption.OntologyQuestion(question="汇总订单并引用口径。", dataset_ids=[dataset], document_ids=[]),
        plan=consumption.QuestionPlan(query_ids=["total"], include_documents=True),
        definition=definition,
        observed_at=datetime(2026, 11, 18, tzinfo=UTC),
    )
    assert citations == [] and unavailable == []
