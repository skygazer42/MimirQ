import asyncio
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.models.registry  # noqa: F401
from app.infrastructure.exceptions import register_exception_handlers
from app.rag.kg.enterprise_ontology import consumption, metrics, objects
from app.rag.kg.enterprise_ontology.consumption import (
    OntologyQuestion,
    QuestionPlan,
    answer_ontology_question,
    grounded_citation,
    plan_question,
)
from app.rag.kg.enterprise_ontology.definition import OntologyDefinition, load_ontology_definition
from app.rag.kg.enterprise_ontology.preview import ChunkPreview, PreviewEntity
from app.rag.kg.extraction.evidence import EvidenceSpan
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.models import LLMResponse
from app.services.chat import enterprise_ontology as chat_ontology
from tests.test_enterprise_ontology_definition import MAINTENANCE_YAML

_OBSERVED_AT = datetime(2026, 11, 23, 12, tzinfo=UTC)


@pytest.mark.parametrize("path", [["first", "second", "third"], ["first", "second", "third", "fourth"]])
def test_ontology_question_accepts_bounded_multi_hop_paths(path):
    plan = QuestionPlan(relation_path=path)
    assert plan.relation_path == path


@pytest.mark.asyncio
async def test_agent_registry_queries_ontology_only_within_trusted_scope(monkeypatch, maintenance_definition):
    from contextlib import nullcontext

    from app.rag.agents.tools import mcp_tools
    from app.rag.agents.tools.mcp_client import DocumentToolScope, MCPToolRegistry

    dataset, document, tenant = uuid4(), uuid4(), uuid4()
    scope = DocumentToolScope(tenant, "reviewer", frozenset({dataset}), frozenset({document}))
    calls = []

    async def ask(db, **kwargs):
        calls.append(kwargs)
        return chat_ontology.OntologyChatTurn(
            answer=consumption.OntologyAnswer(ontology_version_id=uuid4(), plan=QuestionPlan(), answer="1 张"),
            query=OntologyQuestion(question="查询工单"),
        )

    monkeypatch.setattr(chat_ontology, "answer_scoped_ontology", ask)
    monkeypatch.setattr(mcp_tools, "_db_session", lambda: nullcontext(object()))
    monkeypatch.setattr(mcp_tools, "_search_document_scope", lambda *_: [document])
    registry = mcp_tools.register_default_tools(MCPToolRegistry())
    assert "query_ontology" in {tool.name for tool in await registry.list_tools()}

    for rejected_scope, target in ((None, dataset), (scope, uuid4())):
        result = await registry.call_tool(
            "query_ontology", {"question": "查询工单", "dataset_id": str(target)}, scope=rejected_scope
        )
        assert not result.success
    assert calls == []

    result = await registry.call_tool(
        "query_ontology", {"question": "查询工单", "dataset_id": str(dataset)}, scope=scope
    )
    assert result.success and result.data["answer"] == "1 张"
    assert calls[0]["tenant_id"] == tenant and calls[0]["document_ids"] == [document]


@pytest.mark.parametrize("dimension", ["equipment_id", "factory_id"])
def test_grouped_plan_omits_null_filter_placeholders_and_keeps_filter_values(dimension):
    plan = QuestionPlan.model_validate(
        {
            "metric_id": "overdue_count",
            "metric_query": {
                "group_by": [dimension],
                "filters": {"equipment_id": None, "is_priority": False, "retry_count": 0},
            },
        }
    )
    assert plan.metric_query.group_by == [dimension]
    assert plan.metric_query.filters == {"is_priority": False, "retry_count": 0}


@pytest.mark.asyncio
async def test_bound_ontology_keeps_document_selection_inside_the_bound_dataset(monkeypatch):
    dataset_id, document_id = uuid4(), uuid4()

    def unexpected_lookup(*_args):
        pytest.fail("A document outside the selected dataset must not activate that ontology")

    monkeypatch.setattr(chat_ontology, "active_version_id", unexpected_lookup)
    with Session() as db:
        monkeypatch.setattr(db, "scalars", lambda _statement: [])
        turn = await chat_ontology.answer_scoped_ontology(
            db,
            tenant_id=uuid4(),
            account_id="reviewer",
            dataset_id=dataset_id,
            message="指出工单所用设备。",
            document_ids=[document_id],
        )
    assert turn is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    ("截至目前，本月逾期工单按设备分组有多少？", "本月到期且现在逾期的工单有几张？"),
)
async def test_explicit_current_time_discards_the_planners_historical_state(maintenance_definition, question):
    class Client:
        async def chat_with_schema(self, *_args, **_kwargs):
            return {
                "metric_id": "overdue_count",
                "metric_period": "current_month",
                "as_of": _OBSERVED_AT.isoformat(),
                "metric_query": {"group_by": ["equipment_id"], "historical_state": True},
            }

    plan = await plan_question(
        maintenance_definition,
        OntologyQuestion(question=question, observed_at=_OBSERVED_AT),
        Client(),
    )
    assert plan.as_of is None and not plan.metric_query.historical_state


@pytest.fixture
def maintenance_definition():
    payload = load_ontology_definition(MAINTENANCE_YAML, format="yaml").model_dump(mode="json", by_alias=True)
    payload["object_types"]["equipment"]["label"] = "设备"
    payload["metrics"] = {
        "overdue_count": {
            "object_type": "work_order",
            "property": "order_id",
            "aggregate": "count_distinct",
            "time_property": "due_at",
            "timezone": "America/Los_Angeles",
            "allowed_filters": ["equipment_id"],
            "required_filters": {"status": "OPEN"},
            "before_observation": True,
            "label": "逾期工单数",
        }
    }
    payload["functions"] = {"count_overdue": {"metric": "overdue_count", "label": "统计逾期"}}
    return OntologyDefinition.model_validate(payload)


@pytest.fixture
def named_equipment(monkeypatch, maintenance_definition):
    payload = maintenance_definition.model_dump(mode="json", by_alias=True)
    payload["object_types"]["equipment"]["properties"].update(terminal="string", state="string", vendor="string")
    binding = payload["bindings"][0]
    binding["columns"].update(terminal="terminal", state="state", vendor="vendor")
    binding["row_access_column"] = "visible_to"
    definition = OntologyDefinition.model_validate(payload)
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute(
            "CREATE TABLE assets (id TEXT, name TEXT, terminal TEXT, state TEXT, vendor TEXT, visible_to TEXT)"
        )
        connection.executemany(
            "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("E-101", "消防泵", "T1", "可用", "北辰保障", "reader"),
                ("E-201", "消防泵", "T2", "维修", "南辰保障", "reader"),
                ("E-301", "消防泵", "T1", "维修", "其他公司", "other"),
            ],
        )
        monkeypatch.setattr(
            objects,
            "authorized_snapshot",
            lambda *_a, **_k: (
                SimpleNamespace(id=uuid4(), dataset_id=uuid4(), updated_at=None),
                SimpleNamespace(sql_table="assets", table_id="test"),
                {"id", "name", "terminal", "state", "vendor", "visible_to"},
            ),
        )

        def query(**kwargs):
            return {
                "rows": connection.execute(kwargs["sql"], kwargs["parameters"]).fetchall(),
                "truncated": False,
            }

        monkeypatch.setattr(objects, "run_table_query", query)
        yield definition


def test_name_lookup_keeps_location_qualifier_and_row_access(named_equipment):
    matches, complete = objects.find_objects_by_name(
        None,
        tenant_id=uuid4(),
        account_id="reader",
        definition=named_equipment,
        object_type="equipment",
        name="消防泵",
        filters={"terminal": "T1"},
    )
    assert complete and [item.key for item in matches] == [{"equipment_id": "E-101"}]
    assert matches[0].attributes["state"] == "可用"
    assert matches[0].attributes["vendor"] == "北辰保障"


def test_ambiguous_object_choices_keep_only_the_identity_and_display_name(named_equipment):
    result = consumption.execute_question_plan(
        None,
        definition=named_equipment,
        version_id=uuid4(),
        tenant_id=uuid4(),
        account_id="reader",
        request=OntologyQuestion(question="请查询消防泵的状态。"),
        plan=QuestionPlan(object_type="equipment", object_name="消防泵", include_object=True),
    )
    assert len(result.object_choices) == 2
    assert {tuple(item.attributes) for item in result.object_choices} == {("equipment_id", "name")}
    assert {item.key["equipment_id"] for item in result.object_choices} == {"E-101", "E-201"}


@pytest.mark.asyncio
async def test_display_name_in_object_filters_still_resolves_the_named_object(named_equipment):
    class Client:
        async def chat_with_schema(self, *_args, **_kwargs):
            return {
                "object_type": "equipment",
                "object_filters": {"name": "消防泵", "terminal": "T1"},
                "include_object": True,
            }

    request = OntologyQuestion(question="查T1消防泵的台账状态和承包商。")
    plan = await plan_question(named_equipment, request, Client())
    result = consumption.execute_question_plan(
        None,
        definition=named_equipment,
        version_id=uuid4(),
        tenant_id=uuid4(),
        account_id="reader",
        request=request,
        plan=plan,
    )
    assert result.object is not None and result.object.key == {"equipment_id": "E-101"}
    assert result.object.attributes["vendor"] == "北辰保障"


def test_named_object_execution_uses_explicit_location_without_a_followup(named_equipment):
    result = consumption.execute_question_plan(
        None,
        definition=named_equipment,
        version_id=uuid4(),
        tenant_id=uuid4(),
        account_id="reader",
        request=OntologyQuestion(question="查询T1消防泵的状态和承包商。"),
        plan=QuestionPlan(
            object_type="equipment",
            object_name="消防泵",
            object_filters={"terminal": "T1"},
            include_object=True,
        ),
    )
    assert result.object.key == {"equipment_id": "E-101"}
    assert result.object.attributes["vendor"] == "北辰保障"
    assert not result.object_choices


def test_object_bound_query_resolves_a_display_name_without_a_main_object(monkeypatch, named_equipment):
    from app.rag.kg.enterprise_ontology import queries
    from app.rag.kg.enterprise_ontology.definition import NamedQueryDefinition

    definition = named_equipment
    definition.named_queries["state"] = NamedQueryDefinition(
        label="设备状态",
        description="按主键或名称读取状态",
        objects=["equipment"],
        sql="SELECT equipment_id,state FROM equipment WHERE equipment_id=:id",
        parameters={"id": {"type": "string", "object_type": "equipment"}},
    )
    # A unique declared display name must bind to its business key before query execution.
    record = objects.BusinessObject(
        tenant_id=uuid4(),
        ontology=definition.ontology,
        object_type="equipment",
        namespace="assets",
        key={"equipment_id": "E-101"},
        attributes={"name": "T1消防泵"},
        asset_id="ops.equipment",
        source_updated_at=None,
    )
    monkeypatch.setattr(
        queries,
        "authorized_snapshot",
        lambda *_a, **_kw: (
            SimpleNamespace(id=uuid4(), dataset_id=uuid4()),
            SimpleNamespace(sql_table="assets", truncated=False),
            {"id", "name", "terminal", "state", "vendor", "visible_to"},
        ),
    )
    monkeypatch.setattr(
        queries,
        "read_business_object",
        lambda *_a, **_kw: (_ for _ in ()).throw(HTTPException(status_code=404, detail="missing key")),
        raising=False,
    )
    monkeypatch.setattr(queries, "find_objects_by_name", lambda *_a, **_kw: ([record], True), raising=False)
    monkeypatch.setattr(
        queries,
        "run_table_query",
        lambda **kw: {
            "columns": ["equipment_id", "state"],
            "rows": [["E-101", "可用"]] if kw["parameters"]["id"] == "E-101" else [],
            "sql": kw["sql"],
            "truncated": False,
        },
    )
    answer = queries.run_named_query(
        None,
        definition=definition,
        tenant_id=uuid4(),
        account_id="reader",
        query_id="state",
        parameters={"id": "T1消防泵"},
    )
    assert answer.parameters["id"] == "E-101" and answer.rows == [["E-101", "可用"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("filters", [{"missing": "T1"}, {"terminal": "T2"}])
async def test_object_plan_rejects_unknown_or_ungrounded_qualifiers(named_equipment, filters):
    class Client:
        async def chat_with_schema(self, *_args, **_kwargs):
            return {"object_type": "equipment", "object_name": "消防泵", "object_filters": filters}

    with pytest.raises(consumption.InvalidOntologyPlanError):
        await plan_question(named_equipment, OntologyQuestion(question="查询T1消防泵的状态。"), Client())


@pytest.mark.asyncio
async def test_unanchored_query_does_not_apply_single_object_qualifiers(maintenance_definition):
    class Client:
        async def chat_with_schema(self, *_args, **_kwargs):
            return {
                "object_type": "work_order",
                "object_filters": {"due_at": "2026-11-21"},
                "include_documents": True,
            }

    plan = await plan_question(
        maintenance_definition,
        OntologyQuestion(question="2026-11-21应使用哪版制度？"),
        Client(),
    )
    assert plan.object_type is None and plan.object_filters == {} and plan.include_documents


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "metric_selected", "expected_metric", "expected_function"),
    [
        ("本月设备 E-102 有多少张逾期工单？", False, "overdue_count", None),
        ("本月设备 E-102 有多少张逾期工单？", True, "overdue_count", None),
        ("请运行 count_overdue。", False, None, "count_overdue"),
        ("请运行统计逾期。", False, None, "count_overdue"),
    ],
)
async def test_question_uses_metric_unless_user_names_its_function(
    maintenance_definition, question, metric_selected, expected_metric, expected_function
):
    class Client:
        async def chat_with_schema(self, *_args, **_kwargs):
            return {
                "metric_id": "overdue_count" if metric_selected else None,
                "metric_candidates": ["overdue_count"],
                "function_id": "count_overdue",
            }

    plan = await plan_question(maintenance_definition, OntologyQuestion(question=question), Client())

    assert (plan.metric_id, plan.function_id) == (expected_metric, expected_function)


def test_citation_requires_exact_business_object_and_current_excerpt():
    content = "设备 E-102 的维修工单按截止时间判定。"
    chunk = SimpleNamespace(id=uuid4(), document_id=uuid4(), page_number=3, content=content)
    stored = ChunkPreview(
        document_id=chunk.document_id,
        chunk_id=chunk.id,
        page=chunk.page_number,
        entities=[
            PreviewEntity(
                id="E1",
                name="设备 E-102",
                object_type="equipment",
                evidence=EvidenceSpan(quote="设备 E-102", start_char=0, end_char=8, source="quote"),
            )
        ],
    )
    citation = grounded_citation(stored, chunk.content, object_type="equipment", business_key="E-102")
    assert citation is not None and citation.quote == content
    assert grounded_citation(stored, chunk.content, object_type="equipment", business_key="E-1020") is None
    assert grounded_citation(stored, "改版：" + content, object_type="equipment", business_key="E-102") is None
    stored.entities[0].key_fields = ["equipment_id"]
    assert grounded_citation(stored, chunk.content, object_type="equipment", business_key="E-102") is not None
    stored.entities[0].name = "设备"
    assert grounded_citation(stored, chunk.content, object_type="equipment", business_key="设备") is None


@pytest.mark.asyncio
async def test_explicit_object_and_relation_override_conflicting_model_guess():
    class Client:
        calls = 0

        async def chat_with_schema(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"metric_period": "month"}
            return {
                "object_type": "work_order",
                "business_key": "E-102",
                "relation_id": None,
                "metric_query": {"filters": None, "historical_state": None, "observed_at": "model guessed"},
            }

    definition = load_ontology_definition(MAINTENANCE_YAML, format="yaml")
    definition.object_types["equipment"].label = "设备"
    [relation_id] = definition.relation_bindings
    request = OntologyQuestion(question=f"沿 {relation_id} 查询设备 E-102 的工单。")
    client = Client()
    plan = await plan_question(definition, request, client)
    assert (plan.relation_id, plan.object_type, plan.business_key) == (relation_id, "equipment", "E-102")
    assert client.calls == 2 and plan.metric_query.filters == {} and plan.metric_query.observed_at is None


@pytest.mark.asyncio
async def test_multiple_observation_times_are_rejected_before_model_call(maintenance_definition):
    class Client:
        async def chat_with_schema(self, *_args, **_kwargs):
            pytest.fail("An unsupported observation-time request must not call the model")

    request = OntologyQuestion(
        question="同时给出截至 2026 年 11 月 10 日与截至 2026 年 11 月 11 日设备 E-102 的逾期数量。"
    )

    with pytest.raises(consumption.MultipleObservationTimes, match="一次查询仅支持一个历史观察时点") as caught:
        await plan_question(maintenance_definition, request, Client())
    assert caught.value.status_code == 422


@pytest.mark.asyncio
async def test_ontology_planner_deadline_includes_schema_retry(monkeypatch, maintenance_definition):
    class Client:
        calls = 0

        async def chat_with_schema(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"metric_period": "invalid"}
            await asyncio.Event().wait()

    monkeypatch.setattr(consumption, "_PLANNER_TIMEOUT_SECONDS", 0.01)
    client = Client()
    with pytest.raises(consumption.OntologyPlannerTimeoutError) as error:
        await asyncio.wait_for(
            plan_question(maintenance_definition, OntologyQuestion(question="查询逾期工单数量。"), client),
            timeout=1,
        )

    assert error.value.status_code == 504
    assert client.calls == 2


def test_ontology_planner_timeout_returns_public_error():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/ask")
    def ask():
        raise consumption.OntologyPlannerTimeoutError()

    with TestClient(app) as client:
        response = client.get("/ask")

    assert response.status_code == 504
    assert response.json()["error"] == "ONTOLOGY_PLANNER_TIMEOUT"
    assert response.json()["message"] == consumption.ONTOLOGY_PLANNER_TIMEOUT_DETAIL


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "name", "literal", "as_of_utc"),
    [
        ("metric_id", "overdue_count", "2026 年 11 月 10 日", "2026-11-10T08:00:00Z"),
        ("function_id", "count_overdue", "2026-11-10T09:30:00+02:00", "2026-11-10T07:30:00Z"),
        ("metric_id", "overdue_count", "2026-11-01T01:30:00-08:00", "2026-11-01T09:30:00Z"),
    ],
)
@pytest.mark.parametrize("history_available", [True, False])
@pytest.mark.parametrize("confirmed_only", [True, False])
async def test_named_metric_and_function_share_historical_time_with_policy(
    monkeypatch, maintenance_definition, field, name, literal, as_of_utc, history_available, confirmed_only
):
    as_of = datetime.fromisoformat(as_of_utc)
    if history_available:
        maintenance_definition.bindings[1].snapshot_observed_at = as_of
    tenant_id, dataset_id, version_id = uuid4(), uuid4(), uuid4()
    request = OntologyQuestion(
        question=(
            f"截至 {literal}，设备 E-102 的 {name} 是多少？"
            + ("只引用当时已生效的维修制度。" if confirmed_only else "依据哪版维修制度？")
        ),
        dataset_ids=[dataset_id],
        observed_at=_OBSERVED_AT,
    )

    class Client:
        async def chat_with_schema(self, *_args, **_kwargs):
            return {
                field: name,
                "as_of": "2026-11-22" if field == "metric_id" else None,
                "metric_query": {"observed_at": "2026-11-22T00:00:00Z"},
                "include_documents": False,
            }

    # These are the authorized snapshot, object and document records returned by external storage.
    rows = []
    previews = {}
    transition = "2026-11-10" if field == "function_id" else "2026-11-11"
    for filename, metadata in (
        ("历史制度.pdf", {"expires_at": transition}),
        ("现行制度.pdf", {"effective_at": transition}),
    ):
        doc = SimpleNamespace(id=uuid4(), filename=filename, doc_metadata=metadata)
        chunk = SimpleNamespace(id=uuid4(), content="设备 E-102 的维修制度。", page_number=2)
        preview = ChunkPreview(
            document_id=doc.id,
            chunk_id=chunk.id,
            page=chunk.page_number,
            entities=[
                PreviewEntity(
                    id="equipment-1",
                    name="设备 E-102",
                    object_type="equipment",
                    evidence=EvidenceSpan(quote="设备 E-102", start_char=0, end_char=8, source="quote"),
                )
            ],
        )
        rows.append((SimpleNamespace(pipeline_hash="legacy"), doc))
        previews[doc.id] = [(preview, chunk)]

    def query_snapshot(**_kwargs):
        assert history_available, "An unavailable snapshot must skip the aggregate query"
        return {"rows": [[7]], "truncated": False}

    monkeypatch.setattr(consumption, "read_business_object", lambda *args, **kwargs: SimpleNamespace(key=kwargs["key"]))
    monkeypatch.setattr(consumption, "get_dataset", lambda *args: None)
    monkeypatch.setattr(consumption, "assert_dataset_readable", lambda *args: None)
    monkeypatch.setattr(consumption, "active_version_id", lambda *args: version_id)
    monkeypatch.setattr(consumption, "list_accessible_document_ids", lambda *args, **kwargs: list(previews))
    monkeypatch.setattr(consumption, "current_document_previews", lambda _db, _row, doc: previews[doc.id])
    monkeypatch.setattr(
        metrics,
        "authorized_snapshot",
        lambda *_args, **_kwargs: (
            SimpleNamespace(dataset_id=dataset_id, updated_at=_OBSERVED_AT),
            SimpleNamespace(table_id="export", sql_table="sheet_0", truncated=False),
            {"id", "asset_id", "deadline", "state"},
        ),
    )
    monkeypatch.setattr(metrics, "run_table_query", query_snapshot)

    with Session() as db:
        monkeypatch.setattr(db, "execute", lambda _statement: rows)
        answer = await answer_ontology_question(
            db,
            definition=maintenance_definition,
            version_id=version_id,
            tenant_id=tenant_id,
            account_id="reviewer",
            request=request,
            llm_client=Client(),
        )

    metric = answer.metric if field == "metric_id" else answer.function.result
    assert metric.query.observed_at == as_of
    assert metric.query.historical_state
    if confirmed_only:
        assert not answer.citations
        assert "未找到可核验的文档证据" in answer.unavailable
    else:
        [citation] = answer.citations
        assert citation.filename == "历史制度.pdf"
        assert citation.applicability == "pending"
        assert "适用时间待确认" in answer.answer
    if history_available:
        assert metric.complete and metric.value == 7
    else:
        assert metric.value is None and metric.reason == "historical_state_unavailable"
        assert "缺少对应观察时点的历史状态" in answer.unavailable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "candidate"),
    [
        ("查 2026-11-10 至 2026-11-12 的 overdue_count。", "2026-11-10"),
        ("截至现在，查本月的 overdue_count。", "现在"),
    ],
)
async def test_metric_period_does_not_become_a_model_invented_observation_time(
    maintenance_definition, question, candidate
):
    class Client:
        async def chat_with_schema(self, *_args, **_kwargs):
            return {"metric_id": "overdue_count", "as_of": candidate, "metric_period": "current_month"}

    request = OntologyQuestion(question=question, observed_at=_OBSERVED_AT)
    plan = await plan_question(maintenance_definition, request, Client())
    payload = plan.model_dump(mode="json")
    assert "as_of" not in payload and payload["metric_query"] is None
    query = consumption._planned_metric_query(maintenance_definition, "overdue_count", plan, request.observed_at)
    assert query.observed_at == _OBSERVED_AT and not query.historical_state
    assert query.start.isoformat() == "2026-11-01T00:00:00-07:00"
    assert query.end.isoformat() == "2026-12-01T00:00:00-08:00"


@pytest.mark.asyncio
async def test_unresolved_historical_reference_does_not_read_current_count(monkeypatch, maintenance_definition):
    class Client:
        async def chat_with_schema(self, *_args, **_kwargs):
            return {"metric_id": "overdue_count", "as_of": "上周五"}

    monkeypatch.setattr(
        consumption,
        "evaluate_snapshot_metric",
        lambda *args, **kwargs: pytest.fail("An unresolvable historical reference must not use current data"),
    )
    with Session() as db:
        answer = await answer_ontology_question(
            db,
            definition=maintenance_definition,
            version_id=uuid4(),
            tenant_id=uuid4(),
            account_id="reviewer",
            request=OntologyQuestion(question="截至上周五，overdue_count 是多少？", observed_at=_OBSERVED_AT),
            llm_client=Client(),
        )
    assert answer.metric is None and answer.unavailable == ["缺少对应观察时点的历史状态"]


@pytest.fixture
def bound_chat(monkeypatch, maintenance_definition):
    dataset_id, version_id = uuid4(), uuid4()
    version = SimpleNamespace(
        id=version_id, ontology_id=uuid4(), definition=maintenance_definition.model_dump(mode="json", by_alias=True)
    )
    monkeypatch.setattr(chat_ontology, "active_version_id", lambda *args: version_id)
    monkeypatch.setattr(chat_ontology, "published_version", lambda *args: version)

    class Client(BaseLLMClient):
        def __init__(self, output):
            self.output = output
            self.closed = False

        async def chat(self, *_args, **_kwargs):
            if isinstance(self.output, Exception):
                raise self.output
            return LLMResponse(content=self.output)

        def chat_stream(self, *_args, **_kwargs):
            raise AssertionError("Ontology planning should use one-shot structured output")

        async def aclose(self):
            self.closed = True

    async def ask(db, message, output):
        client = Client(output)

        async def create_client():
            return client

        monkeypatch.setattr(chat_ontology, "create_llm_client", create_client)
        try:
            return await chat_ontology.answer_scoped_ontology(
                db, tenant_id=uuid4(), account_id="reviewer", dataset_id=dataset_id, message=message, document_ids=[]
            )
        finally:
            assert client.closed

    return ask


@pytest.mark.asyncio
@pytest.mark.parametrize("output", ['{"metric_period":"month"}', "[]", RuntimeError("provider quota exceeded")])
async def test_bound_chat_falls_through_for_normal_questions_after_planner_failure(bound_chat, output):
    with Session() as db:
        answer = await bound_chat(db, "维修流程有哪些注意事项？", output)
    assert answer is None


@pytest.mark.asyncio
async def test_bound_chat_falls_through_for_undeclared_named_queries(bound_chat, monkeypatch):
    monkeypatch.setattr(chat_ontology.settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True)
    with Session() as db:
        answer = await bound_chat(db, "维修流程有哪些注意事项？", '{"query_ids":["invented_query"]}')
    assert answer is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "output", "reason"),
    [
        ("设备 E-102 的工单有几张？", "[]", "ontology_planner_invalid"),
        ("查询逾期工单数", '{"metric_period":"month"}', "ontology_planner_invalid"),
        ("请执行 count_overdue", "invalid JSON", "ontology_planner_invalid"),
        ("How many work orders exist?", RuntimeError("provider quota exceeded"), "model_provider_unavailable"),
    ],
)
async def test_bound_chat_shows_requested_count_as_unavailable_after_planner_failure(
    bound_chat, question, output, reason
):
    with Session() as db:
        turn = await bound_chat(db, question, output)
        stored = SimpleNamespace(
            id=uuid4(),
            role="assistant",
            created_at=_OBSERVED_AT,
            message_metadata=turn.receipt_metadata,
        )
        visible = chat_ontology.visible_ontology_message(db, tenant_id=uuid4(), account_id="reviewer", message=stored)

    assert turn.answer.unavailable and turn.answer.metric is None and turn.citations == []
    assert "不可用" in turn.answer.answer
    assert visible.content == turn.answer.answer
    assert turn.receipt_metadata == {"ontology_query": {"planner_failure": reason}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "reason"),
    (
        (consumption.OntologyPlannerTimeoutError(), "ontology_planner_timeout"),
        (consumption.MultipleObservationTimes(), "multiple_observation_times"),
    ),
)
async def test_bound_chat_preserves_request_failure_in_history(bound_chat, error, reason):
    message = "工单 WO-01 关联的设备在哪条产线？"
    with Session() as db:
        turn = await bound_chat(db, message, error)
        stored = SimpleNamespace(
            id=str(uuid4()), role="assistant", created_at=_OBSERVED_AT, message_metadata=turn.receipt_metadata
        )
        visible = chat_ontology.visible_ontology_message(db, message=stored, tenant_id=uuid4(), account_id="reviewer")

    assert turn.planner_failure == reason
    assert turn.answer.answer == visible.content
    assert visible.content in {
        consumption.ONTOLOGY_PLANNER_TIMEOUT_DETAIL,
        consumption.MULTIPLE_OBSERVATION_TIMES_DETAIL,
    }
    assert visible.citations == [] and visible.ontology_action is None


@pytest.mark.asyncio
async def test_bound_chat_propagates_request_authorization_errors(bound_chat):
    with Session() as db, pytest.raises(HTTPException) as error:
        await bound_chat(db, "维修流程有哪些注意事项？", HTTPException(status_code=403, detail="Access denied"))
    assert error.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "action_id", "reason", "expected_action", "expected"),
    [
        ("预演 close_order 关闭维修工单 WO-01。", "close_order", "预演关闭", "close_order", {}),
        (
            "预演 close_order，关闭维修工单 WO-01，关闭原因是 done。",
            "close_order",
            "done",
            "close_order",
            {"reason": "done"},
        ),
        (
            "不要执行，只预演 close_order 关闭工单 WO-01，原因是处理完成。",
            "close_order",
            "处理完成",
            "close_order",
            {"reason": "处理完成"},
        ),
        ("请说明 close_order 的用途，不要为维修工单 WO-01 预演或执行这个动作。", "close_order", None, None, {}),
        ("为什么要审批 close_order？以维修工单 WO-01 举例。", None, None, None, {}),
    ],
)
async def test_action_plan_preserves_intent_and_user_supplied_text(
    question, action_id, reason, expected_action, expected, maintenance_definition
):
    payload = maintenance_definition.model_dump(mode="json", by_alias=True)
    payload["actions"] = {
        "close_order": {
            "object_type": "work_order",
            "target": "maintenance",
            "parameters": {"reason": {"type": "string", "required": True}},
        },
    }
    definition = OntologyDefinition.model_validate(payload)

    class Client:
        async def chat_with_schema(self, *_args, **_kwargs):
            return {
                "object_type": "work_order",
                "business_key": "WO-01",
                "action_id": action_id,
                "action_parameters": {"reason": reason} if reason else {},
            }

    plan = await plan_question(definition, OntologyQuestion(question=question), Client())

    assert plan.action_id == expected_action
    assert plan.business_key == "WO-01"
    assert plan.action_parameters == expected


def test_planner_omits_null_action_parameters_but_preserves_false_and_zero():
    plan = QuestionPlan.model_validate({"action_parameters": {"reason": None, "notify": False, "amount": 0}})
    assert plan.action_parameters == {"notify": False, "amount": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "expected_groups"),
    [
        ("设备 E-102 本月的逾期工单数，排除已经关闭的工单和还没到期的工单。", []),
        ("设备 E-102 本月的逾期工单数，按设备分组。", ["equipment_id"]),
    ],
)
async def test_count_does_not_group_by_the_selected_object_unless_requested(
    maintenance_definition, question, expected_groups
):
    class Client:
        async def chat_with_schema(self, *_args, **_kwargs):
            return {
                "metric_id": "overdue_count",
                "object_type": "equipment",
                "business_key": "E-102",
                "metric_query": {"filters": {"equipment_id": "E-102"}, "group_by": ["equipment_id"]},
            }

    plan = await plan_question(maintenance_definition, OntologyQuestion(question=question), Client())

    assert plan.metric_query.group_by == expected_groups
    assert plan.metric_query.filters == {"equipment_id": "E-102"}


@pytest.mark.parametrize(
    ("question", "expected_as_of"),
    [
        ("核对 2026-10-30 当天 E-102 的指标，并引用已生效的制度。", "2026-10-30"),
        ("核对 2026 年 10 月 30 日当天的指标，只引用仍有效的制度。", "2026 年 10 月 30 日"),
        ("统计 2026-10-30 当天到期的工单，并引用已生效的制度。", None),
    ],
)
def test_policy_observation_uses_explicit_historical_day_except_for_due_window(question, expected_as_of):
    assert consumption._grounded_as_of(question, None) == expected_as_of


def test_planner_accepts_current_month_nested_in_grouped_metric_query():
    plan = QuestionPlan.model_validate(
        {"metric_id": "overdue_count", "metric_query": {"metric_period": "current_month", "group_by": ["equipment_id"]}}
    )
    assert plan.metric_period == "current_month"
    assert plan.metric_query.group_by == ["equipment_id"]


def test_planner_null_qualifiers_are_absent_from_saved_receipts():
    plan = QuestionPlan.model_validate({"object_filters": None})
    assert plan.object_filters == {}
    assert "object_filters" not in plan.model_dump(mode="json")


def test_chat_action_proposal_uses_only_published_fields():
    definition = OntologyDefinition.model_validate(
        {
            "schema_version": 1,
            "ontology": "maintenance",
            "object_types": {
                "order": {"key": ["number"], "properties": {"number": {"type": "string", "label": "工单号"}}}
            },
            "bindings": [
                {
                    "object_type": "order",
                    "role": "primary",
                    "asset_id": "orders",
                    "identity_columns": ["number"],
                    "columns": {"number": "number"},
                }
            ],
            "actions": {
                "close": {
                    "object_type": "order",
                    "target": "maintenance",
                    "label": "关闭工单",
                    "approval_required": True,
                    "parameters": {"reason": {"type": "string", "required": True}, "notify": {"type": "boolean"}},
                }
            },
        }
    )
    version = SimpleNamespace(id=uuid4(), ontology_id=uuid4())
    plan = QuestionPlan(
        object_type="order",
        business_key="WO-01",
        action_id="close",
        action_parameters={"notify": False, "unknown": "discard"},
    )

    proposal = chat_ontology.build_action_proposal(version.ontology_id, version.id, definition, plan)
    assert proposal is not None
    assert proposal.key == {"number": "WO-01"}
    assert proposal.key_fields == {"number": "工单号"}
    assert proposal.parameters == {"notify": False}
    assert proposal.parameter_fields["reason"].required
    assert proposal.approval_required
    assert (
        chat_ontology.build_action_proposal(
            version.ontology_id, version.id, definition, plan.model_copy(update={"object_type": "other"})
        )
        is None
    )
