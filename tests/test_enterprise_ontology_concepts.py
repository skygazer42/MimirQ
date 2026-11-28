from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.rag.kg.enterprise_ontology import consumption
from app.rag.kg.enterprise_ontology.definition import OntologyDefinition
from app.rag.kg.enterprise_ontology.documents import save_document_evidence
from app.rag.kg.enterprise_ontology.preview import ChunkPreview
from app.rag.kg.enterprise_ontology.versions import publish_version
from app.rag.runtime.graph.context import build_grounded_context
from app.services.chat import enterprise_ontology as chat
from tests.test_enterprise_ontology_activation import _activate, _chunk, _document, activation  # noqa: F401
from tests.test_enterprise_ontology_fusion import query_definition


def test_published_definition_accepts_a_concept_with_explicit_sources():
    payload = query_definition("fixture").model_dump(mode="json", by_alias=True)
    source = uuid4()
    payload["concepts"] = {
        "assistance": {"label": "旅客服务", "description": "申请与保障制度。", "sources": [str(source)]},
    }
    definition = OntologyDefinition.model_validate(payload)
    assert definition.concepts["assistance"].sources == [source]


@pytest.fixture
def concept_release(activation):  # noqa: F811 - pytest resolves the shared fixture by name.
    db, client, dataset, workspace = activation
    policy = _document(db, dataset)
    policy.filename = "特殊旅客服务规范.md"
    policy.status = "completed"
    policy.publication_status = "published"
    text = "担架服务应提前四十八小时申请，轮椅申请不能代替担架审批。"
    chunk = _chunk(db, policy, 0, "approved")
    chunk.content = text
    historical = _chunk(db, policy, 1, "historical")
    historical.content = "已经停用的旧处理说明。"
    db.commit()
    payload = {
        **workspace.draft,
        "concepts": {
            "special_assistance": {
                "label": "特殊旅客服务",
                "aliases": ["担架", "轮椅"],
                "description": "特殊旅客申请、材料与保障安排的制度依据。",
                "sources": [str(policy.id)],
            },
        },
    }
    definition = OntologyDefinition.model_validate(payload)
    version = publish_version(db, workspace, expected_revision=1, account_id="reviewer", frozen_definition=definition)
    save_document_evidence(
        db,
        tenant_id=dataset.tenant_id,
        document=policy,
        version_id=version.id,
        pipeline_hash="approved",
        previews=[ChunkPreview(document_id=policy.id, chunk_id=chunk.id, page=1)],
    )
    assert _activate(client, dataset, version).status_code == 200
    return SimpleNamespace(
        db=db,
        client=client,
        dataset=dataset,
        version=version,
        definition=definition,
        policy=policy,
        chunk=chunk,
        text=text,
    )


def test_empty_concept_fields_preserve_existing_receipt_serialization():
    assert "concept_ids" not in consumption.QuestionPlan().model_dump(mode="json")


@pytest.mark.asyncio
@pytest.mark.parametrize("concept", ["special_assistance", "invented"])
async def test_planner_selects_only_published_concepts_without_an_object(concept_release, concept):
    class Client:
        calls = 0

        async def chat_with_schema(self, *_args, **_kwargs):
            self.calls += 1
            return {"concept_ids": [concept]}

    client = Client()
    request = consumption.OntologyQuestion(question="设备的担架服务怎么处理？")
    if concept == "invented":
        with pytest.raises(consumption.InvalidOntologyPlanError):
            await consumption.plan_question(concept_release.definition, request, client)
        assert client.calls == 2
    else:
        plan = await consumption.plan_question(concept_release.definition, request, client)
        assert plan.concept_ids == [concept] and plan.business_key is None
        assert client.calls == 1


@pytest.mark.asyncio
async def test_published_concept_alias_uses_its_source_without_a_model_planner(concept_release):
    class PlannerMustNotRun:
        async def chat_with_schema(self, *_args, **_kwargs):
            pytest.fail("A source-bound policy concept has no query to plan")

    request = consumption.OntologyQuestion(question="担架提前申请需要哪些条件？")
    plan = await consumption.plan_question(concept_release.definition, request, PlannerMustNotRun())
    assert plan.concept_ids == ["special_assistance"] and plan.include_documents
    assert plan.query_ids == [] and plan.business_key is None and plan.action_id is None


@pytest.mark.asyncio
async def test_concept_alias_does_not_shortcut_an_explicit_count_request(concept_release):
    calls = []

    class Planner:
        async def chat_with_schema(self, _messages, **_kwargs):
            calls.append("planned")
            return {"concept_ids": ["special_assistance"], "query_ids": ["preview_count"]}

    definition = concept_release.definition.model_copy(deep=True)
    definition.named_queries = query_definition("unbound:orders").named_queries
    definition.named_queries["preview_count"] = definition.named_queries["total"].model_copy(
        update={"label": "已提交的担架申请数量", "parameters": {}},
    )
    plan = await consumption.plan_question(
        definition,
        consumption.OntologyQuestion(question="按制度，担架服务需要提前多久申请？本批申请有多少项？"),
        Planner(),
    )
    assert calls == ["planned"] and plan.query_ids == ["preview_count"]


@pytest.mark.asyncio
async def test_concept_mention_does_not_shortcut_a_business_cost_comparison():
    payload = query_definition("unbound:orders").model_dump(mode="json", by_alias=True)
    payload["concepts"] = {
        "delivery_policy": {
            "label": "交期规则",
            "description": "交期规定及例外。",
            "aliases": ["交期"],
            "sources": [str(uuid4())],
        },
    }
    definition = OntologyDefinition.model_validate(payload)
    calls = []

    class Planner:
        async def chat_with_schema(self, _messages, **_kwargs):
            calls.append("planned")
            return {"concept_ids": ["delivery_policy"], "query_ids": ["total"]}

    plan = await consumption.plan_question(
        definition,
        consumption.OntologyQuestion(
            question="甲方设备总价20000元但不满足交期，乙方总成本22000元且符合要求，应该选哪家？"
        ),
        Planner(),
    )
    assert calls == ["planned"] and plan.query_ids == ["total"]


@pytest.mark.parametrize("with_object", [False, True])
def test_concept_reads_current_policy_with_or_without_a_business_object(concept_release, with_object):
    case = concept_release
    plan = consumption.QuestionPlan(concept_ids=["special_assistance"])
    if with_object:
        plan.object_type, plan.business_key = "work_order", "WO-01"
    answer = consumption.execute_question_plan(
        case.db,
        definition=case.definition,
        version_id=case.version.id,
        tenant_id=case.dataset.tenant_id,
        account_id="reviewer",
        request=consumption.OntologyQuestion(
            question="请查担架申请依据。",
            dataset_ids=[case.dataset.id],
            observed_at=datetime(2026, 11, 18, tzinfo=UTC),
        ),
        plan=plan,
    )
    assert not answer.unavailable
    assert [citation.chunk_id for citation in answer.citations] == [case.chunk.id]
    assert answer.citations[0].evidence.quote == case.text
    assert "已经停用" not in answer.answer


def test_concept_cannot_read_outside_selected_documents_or_datasets(concept_release):
    case = concept_release
    for datasets, documents in (([case.dataset.id], []), ([uuid4()], None)):
        citations, _unavailable = consumption.read_ontology_citations(
            case.db,
            tenant_id=case.dataset.tenant_id,
            account_id="reviewer",
            version_id=case.version.id,
            request=consumption.OntologyQuestion(
                question="查询担架规则。", dataset_ids=datasets, document_ids=documents
            ),
            plan=consumption.QuestionPlan(concept_ids=["special_assistance"]),
            definition=case.definition,
            observed_at=datetime(2026, 11, 18, tzinfo=UTC),
        )
        assert citations == []


@pytest.mark.asyncio
async def test_bound_chat_preserves_a_concept_only_plan(concept_release, monkeypatch):
    case = concept_release

    class Client:
        async def chat_with_schema(self, *_args, **_kwargs):
            return {"concept_ids": ["special_assistance"]}

        async def aclose(self):
            pass

    async def create_client():
        return Client()

    monkeypatch.setattr(chat, "create_llm_client", create_client)
    turn = await chat.answer_scoped_ontology(
        case.db,
        tenant_id=case.dataset.tenant_id,
        account_id="reviewer",
        dataset_id=case.dataset.id,
        message="请说明担架申请依据。",
        document_ids=None,
    )
    assert turn is not None and turn.answer.citations[0].document_id == case.policy.id
    evidence = chat.build_ontology_evidence(
        case.db,
        tenant_id=case.dataset.tenant_id,
        account_id="reviewer",
        dataset_ids=[case.dataset.id],
        document_ids=None,
        turn=turn,
    )
    assert evidence.metrics["ontology_used"] and case.text in evidence.documents[0].page_content


def test_archived_concept_policy_is_not_exposed(concept_release):
    case = concept_release
    case.policy.archived_at = datetime.now(UTC)
    case.db.commit()
    citations, _unavailable = consumption.read_ontology_citations(
        case.db,
        tenant_id=case.dataset.tenant_id,
        account_id="reviewer",
        version_id=case.version.id,
        request=consumption.OntologyQuestion(question="查询担架规则。", dataset_ids=[case.dataset.id]),
        plan=consumption.QuestionPlan(concept_ids=["special_assistance"]),
        definition=case.definition,
        observed_at=datetime(2026, 11, 18, tzinfo=UTC),
    )
    assert citations == []


def test_saved_concept_answer_is_hidden_after_source_revocation(concept_release):
    case = concept_release
    request = consumption.OntologyQuestion(question="查询担架规则。", dataset_ids=[case.dataset.id])
    answer = consumption.execute_question_plan(
        case.db,
        definition=case.definition,
        version_id=case.version.id,
        tenant_id=case.dataset.tenant_id,
        account_id="reviewer",
        request=request,
        plan=consumption.QuestionPlan(concept_ids=["special_assistance"]),
    )
    turn = chat.OntologyChatTurn(answer=answer, query=request)
    evidence = chat.build_ontology_evidence(
        case.db,
        tenant_id=case.dataset.tenant_id,
        account_id="reviewer",
        dataset_ids=[case.dataset.id],
        document_ids=None,
        turn=turn,
    )
    context = build_grounded_context(evidence.documents, ontology_context=evidence.context, query=request.question)
    content, citations, metadata = chat.protect_fused_answer(
        case.text,
        chat._citations(answer),
        {**evidence.metrics, "generation_context": context.trace},
    )
    saved = SimpleNamespace(
        id=uuid4(),
        role="assistant",
        content=content,
        citations=citations,
        message_metadata=metadata,
        created_at=datetime.now(UTC),
    )
    visible = chat.visible_ontology_message(
        case.db, tenant_id=case.dataset.tenant_id, account_id="reviewer", message=saved
    )
    assert visible.content == case.text and visible.citations
    case.policy.archived_at = datetime.now(UTC)
    case.db.commit()
    denied = chat.visible_ontology_message(
        case.db, tenant_id=case.dataset.tenant_id, account_id="reviewer", message=saved
    )
    assert case.text not in denied.content and denied.citations == []
