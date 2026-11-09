from uuid import uuid4

import pytest

from app.models.document import Document as DBDocument
from app.rag.pipeline_plugins import contracts, local_runner, runtime
from app.rag.policy import intent_router
from app.rag.tools import mcp_tools
from app.rag.workflows.evaluator_optimizer import EvaluatorOptimizerWorkflow
from app.rag.workflows.react import ReActWorkflow


def metadata_schema() -> dict:
    return {"schema": "mimirq.metadata_schema.v1", "fields": [{"name": "field", "type": "string"}]}


@pytest.mark.parametrize("stage", [0, False])
def test_invalid_metadata_stage_is_not_replaced_by_default_stages(stage: object) -> None:
    schema = metadata_schema()
    schema["fields"][0]["stages"] = [stage]
    with pytest.raises(contracts.PipelinePluginContractError):
        contracts.parse_metadata_schema(schema)


@pytest.mark.parametrize("value", [0, False])
def test_invalid_highlight_metadata_does_not_select_the_key_alias(value: object) -> None:
    with pytest.raises(contracts.PipelinePluginContractError):
        contracts.validate_retrieval_policy_metadata_fields(
            retrieval_policy={
                "schema": "mimirq.retrieval_policy.v1",
                "response_hints": {"answer_highlight_metadata_fields": [{"metadata": value, "key": "field"}]},
            },
            metadata_schema=metadata_schema(),
        )


@pytest.mark.parametrize("value", [0, False])
def test_invalid_anchor_role_is_not_an_omitted_role(value: object) -> None:
    with pytest.raises(contracts.PipelinePluginContractError):
        contracts.validate_retrieval_policy_metadata_fields(
            retrieval_policy={
                "schema": "mimirq.retrieval_policy.v1",
                "anchor_fields": [{"metadata": "field", "role": value}],
            },
            metadata_schema=metadata_schema(),
        )


def test_content_only_retrieval_text_does_not_require_metadata() -> None:
    contracts.validate_retrieval_text_schema_metadata_fields(
        retrieval_text_schema={
            "schema": "mimirq.retrieval_text_schema.v1",
            "stages": {"chunk": {"fields": [{"content": True}]}},
        },
        metadata_schema=metadata_schema(),
    )


@pytest.mark.parametrize("actor", [0, False])
def test_invalid_mcp_actor_is_not_the_omitted_service_context(actor: object) -> None:
    document_id = uuid4()
    document = DBDocument(id=document_id, owner_id="owner", access_mode="only_me")
    with pytest.raises(AttributeError):
        mcp_tools._can_read_document_content(
            object(), document, tenant_id=uuid4(), document_id=document_id, account_id=actor
        )


def test_empty_explicit_mcp_actor_does_not_bypass_private_document_access() -> None:
    document_id = uuid4()
    document = DBDocument(id=document_id, owner_id="owner", access_mode="only_me")
    assert mcp_tools._can_read_document_content(
        object(), document, tenant_id=uuid4(), document_id=document_id, account_id=""
    ) is False


def test_policy_numeric_zero_bool_override_remains_false() -> None:
    result = intent_router.normalize_intent_router_policy(
        {"schema": "mimirq.intent_router_policy.v1", "rules": [
            {"rule_id": "rule", "match_any": ["term"], "overrides": {"enable_reranker": 0}}
        ]}
    )
    assert result is not None
    assert result["rules"][0]["overrides"]["enable_reranker"] is False


def test_policy_scalar_zero_rule_id_and_term_are_not_omitted() -> None:
    result = intent_router.normalize_intent_router_policy(
        {"schema": "mimirq.intent_router_policy.v1", "rules": [
            {"rule_id": 0, "match_any": [0], "overrides": {"enable_reranker": True}}
        ]}
    )
    assert result is not None
    assert result["rules"][0]["rule_id"] == "0"
    assert result["rules"][0]["match_any"] == ["0"]


@pytest.mark.parametrize("value", [0, False, 1, True])
def test_plugin_document_scalar_text_is_preserved(value: object) -> None:
    assert local_runner._coerce_input_document({"content": value}).page_content == str(value)
    assert runtime._coerce_document({"content": value}, stage="chunk", plugin_ref="plugin:example", index=0).page_content == str(value)


def test_plugin_document_requires_a_text_field() -> None:
    with pytest.raises(local_runner.PipelinePluginRegistryError):
        local_runner._coerce_input_document({"metadata": {}})
    with pytest.raises(runtime.PythonPipelinePluginError):
        runtime._coerce_document({"metadata": {}}, stage="chunk", plugin_ref="plugin:example", index=0)


@pytest.mark.parametrize("value", [0, False])
def test_workflow_invalid_question_does_not_select_the_query_alias(value: object) -> None:
    with pytest.raises(TypeError):
        ReActWorkflow().get_question({"question": value, "query": "fallback"})


def test_workflow_explicit_empty_question_is_preserved() -> None:
    assert ReActWorkflow().get_question({"question": "", "query": "fallback"}) == ""


def test_workflow_context_requires_real_content() -> None:
    with pytest.raises(KeyError, match="content"):
        EvaluatorOptimizerWorkflow._heuristic_evaluation("answer", [{}])


def test_empty_workflow_context_does_not_count_as_evidence() -> None:
    no_context = EvaluatorOptimizerWorkflow._heuristic_evaluation("answer", [])
    empty_context = EvaluatorOptimizerWorkflow._heuristic_evaluation("answer", [{"content": ""}])
    assert empty_context.score == no_context.score


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [0, False])
async def test_react_tool_observation_preserves_scalar_results(value: object) -> None:
    async def return_value(_text):
        return value

    workflow = ReActWorkflow()
    workflow.add_tool("value", return_value, "return a value")
    assert await workflow._act({}, "value", "input") == str(value)
